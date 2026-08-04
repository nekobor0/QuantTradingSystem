"""Normalize TdxQuant daily bars and publish them through the existing data layer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from quant_trading_system.market_data import BatchStatus, BarFrequency, RawBarInput, VolumeUnit
from quant_trading_system.market_data.domain import DatasetBatch
from quant_trading_system.market_data.errors import QualityGateRejected
from quant_trading_system.market_data.raw_store import RawFileStore
from quant_trading_system.market_data.service import IngestBarsCommand, MarketDataService

from .errors import TdxProtocolError

SHANGHAI = ZoneInfo("Asia/Shanghai")
AMOUNT_WAN_TO_CNY = Decimal("10000")
REQUIRED_FIELDS = ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")


class DailyHistoryClient(Protocol):
    def get_daily_bars(
        self, symbols: Sequence[str], *, start_time: str, end_time: str
    ) -> Mapping[str, Any]: ...


class TdxIngestionBridge:
    """Historical-only bridge; real-time subscriptions and trading are out of scope."""

    def __init__(
        self,
        client: DailyHistoryClient,
        raw_store: RawFileStore,
        market_data: MarketDataService,
    ) -> None:
        self.client = client
        self.raw_store = raw_store
        self.market_data = market_data

    def backfill(
        self,
        symbols: Sequence[str],
        *,
        start: date,
        end: date,
        received_at: datetime | None = None,
        volume_unit: VolumeUnit = VolumeUnit.SHARES,
    ) -> DatasetBatch:
        if end < start:
            raise TdxProtocolError("end date must not precede start date")
        normalized = tuple(dict.fromkeys(value.strip().upper() for value in symbols if value.strip()))
        if not normalized:
            raise TdxProtocolError("at least one symbol is required")
        received = (received_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        envelope = self.client.get_daily_bars(
            normalized,
            start_time=start.strftime("%Y%m%d"),
            end_time=end.strftime("%Y%m%d"),
        )
        raw_bytes = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        checksum, raw_uri = self.raw_store.put(raw_bytes, ".json")
        records = self._records(
            envelope,
            normalized,
            start=start,
            end=end,
            received_at=received,
            revision=f"tdx-{checksum[:16]}",
            volume_unit=volume_unit,
        )
        batch = self.market_data.ingest_bars(
            IngestBarsCommand("tdx", checksum, raw_uri, records, received)
        )
        if batch.status is not BatchStatus.PUBLISHED:
            raise QualityGateRejected(
                f"existing TdxQuant batch {batch.batch_id} has status {batch.status.value}"
            )
        return batch

    def incremental(
        self,
        symbols: Sequence[str],
        *,
        trading_date: date,
        received_at: datetime | None = None,
        volume_unit: VolumeUnit = VolumeUnit.SHARES,
    ) -> DatasetBatch:
        return self.backfill(
            symbols,
            start=trading_date,
            end=trading_date,
            received_at=received_at,
            volume_unit=volume_unit,
        )

    @classmethod
    def _records(
        cls,
        envelope: Mapping[str, Any],
        symbols: Sequence[str],
        *,
        start: date,
        end: date,
        received_at: datetime,
        revision: str,
        volume_unit: VolumeUnit,
    ) -> tuple[RawBarInput, ...]:
        result = envelope.get("result")
        values = result.get("Value") if isinstance(result, Mapping) else None
        if not isinstance(values, Mapping):
            raise TdxProtocolError("TdxQuant response is missing result.Value")
        records: list[RawBarInput] = []
        empty: list[str] = []
        for symbol in symbols:
            series = values.get(symbol)
            if not isinstance(series, Mapping):
                raise TdxProtocolError(f"TdxQuant response is missing symbol {symbol}")
            error_id = str(series.get("ErrorId", "0"))
            if error_id != "0":
                raise TdxProtocolError(f"TdxQuant symbol {symbol} ErrorId={error_id}")
            lengths = cls._field_lengths(series, symbol)
            if lengths["Date"] == 0:
                empty.append(symbol)
                continue
            if len(set(lengths.values())) != 1:
                raise TdxProtocolError(f"TdxQuant fields have different lengths for {symbol}")
            for index in range(lengths["Date"]):
                trading_date = cls._date(series["Date"][index], symbol)
                if not start <= trading_date <= end:
                    raise TdxProtocolError(f"TdxQuant returned {trading_date} outside requested range")
                bar_end = datetime.combine(trading_date, time(15), SHANGHAI).astimezone(timezone.utc)
                records.append(
                    RawBarInput(
                        source_code=symbol,
                        frequency=BarFrequency.DAY,
                        trading_date=trading_date,
                        bar_end_at=bar_end,
                        available_at=received_at,
                        open=cls._decimal(series["Open"][index], "Open", symbol),
                        high=cls._decimal(series["High"][index], "High", symbol),
                        low=cls._decimal(series["Low"][index], "Low", symbol),
                        close=cls._decimal(series["Close"][index], "Close", symbol),
                        volume=cls._decimal(series["Volume"][index], "Volume", symbol),
                        turnover=cls._decimal(series["Amount"][index], "Amount", symbol)
                        * AMOUNT_WAN_TO_CNY,
                        volume_unit=volume_unit,
                        revision=revision,
                    )
                )
        if empty:
            raise TdxProtocolError(f"TdxQuant returned no daily bars for: {', '.join(empty)}")
        if not records:
            raise TdxProtocolError("TdxQuant returned an empty daily-bar batch")
        return tuple(records)

    @staticmethod
    def _field_lengths(series: Mapping[str, Any], symbol: str) -> dict[str, int]:
        lengths: dict[str, int] = {}
        for field in REQUIRED_FIELDS:
            value = series.get(field)
            if not isinstance(value, list):
                raise TdxProtocolError(f"TdxQuant field {field} is missing for {symbol}")
            lengths[field] = len(value)
        return lengths

    @staticmethod
    def _date(value: Any, symbol: str) -> date:
        text = str(value).strip().split(".", 1)[0].replace("-", "")
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError as exc:
            raise TdxProtocolError(f"invalid Date for {symbol}: {value}") from exc

    @staticmethod
    def _decimal(value: Any, field: str, symbol: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise TdxProtocolError(f"invalid {field} for {symbol}: {value}") from exc
        if not result.is_finite():
            raise TdxProtocolError(f"non-finite {field} for {symbol}")
        return result


def payload_checksum(envelope: Mapping[str, Any]) -> str:
    """Expose the canonical response checksum for diagnostics and tests."""
    payload = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
