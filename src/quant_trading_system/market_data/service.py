"""Quality-gated ingestion and immutable snapshot queries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from quant_trading_system.instruments import InstrumentService

from .domain import (
    AdjustmentFactor, Bar, BatchStatus, DataQualityResult, DatasetBatch, DatasetSnapshot,
    MarketDataEvent, PriceMode, QualitySeverity, RawBarInput, VolumeUnit,
)
from .errors import FactorUnavailable, InvalidMarketData, QualityGateRejected, SnapshotNotFound
from .ports import MarketDataRepository


@dataclass(frozen=True, slots=True)
class IngestBarsCommand:
    source: str
    checksum: str
    raw_uri: str
    records: tuple[RawBarInput, ...]
    received_at: datetime


class MarketDataService:
    FACTOR_DEFINITION = "cumulative backward multiplier"

    def __init__(self, repository: MarketDataRepository, instruments: InstrumentService) -> None:
        self.repository = repository
        self.instruments = instruments

    def ingest_bars(self, command: IngestBarsCommand) -> DatasetBatch:
        existing = self.repository.find_batch(command.source, command.checksum)
        if existing is not None:
            return existing
        batch = DatasetBatch(command.source, command.checksum, command.raw_uri, command.received_at)
        bars: list[Bar] = []
        failures: list[DataQualityResult] = []
        seen: set[tuple[UUID, str, datetime, str]] = set()
        for index, raw in enumerate(command.records):
            try:
                resolved = self.instruments.resolve(command.source, raw.source_code, raw.trading_date)
                if not resolved.tradable:
                    raise InvalidMarketData("instrument is not tradable on trading_date")
                if raw.trading_date.weekday() >= 5:
                    raise InvalidMarketData("non-trading weekday")
                zone = ZoneInfo("Asia/Hong_Kong" if resolved.instrument.exchange.value == "HKEX" else "Asia/Shanghai")
                if raw.bar_end_at.astimezone(zone).date() != raw.trading_date:
                    raise InvalidMarketData("bar_end_at does not match exchange-local trading_date")
                if raw.bar_end_at.astimezone(timezone.utc) > command.received_at.astimezone(timezone.utc):
                    raise InvalidMarketData("future bar is not publishable")
                volume = raw.volume
                if volume is not None and raw.volume_unit is VolumeUnit.LOTS:
                    spec = self.instruments.get_trading_spec(resolved.instrument.instrument_id, raw.trading_date)
                    volume = Decimal(str(volume)) * spec.lot_size
                bar = Bar(
                    resolved.instrument.instrument_id, raw.frequency, raw.trading_date,
                    raw.bar_end_at, raw.available_at, raw.open, raw.high, raw.low, raw.close,
                    volume, raw.turnover, batch.batch_id, raw.revision,
                )
                key = (bar.instrument_id, bar.frequency.value, bar.bar_end_at, bar.revision)
                if key in seen:
                    raise InvalidMarketData("duplicate bar in batch")
                seen.add(key)
                bars.append(bar)
            except Exception as exc:
                failures.append(DataQualityResult("bar-validity", QualitySeverity.ERROR, str(exc), index))
        if not command.records:
            failures.append(DataQualityResult("non-empty", QualitySeverity.ERROR, "batch is empty"))
        if failures:
            self.repository.save_rejected(batch, failures)
            raise QualityGateRejected(f"batch {batch.batch_id} rejected with {len(failures)} error(s)")
        event = MarketDataEvent("DatasetBatchPublished", batch.batch_id, datetime.now(timezone.utc), {"kind": "bars"})
        self.repository.publish(batch, bars, event)
        published = self.repository.get_batch(batch.batch_id)
        assert published is not None
        return published

    def publish_factors(self, batch: DatasetBatch, factors: Sequence[AdjustmentFactor]) -> DatasetBatch:
        existing = self.repository.find_batch(batch.source, batch.checksum)
        if existing is not None:
            return existing
        if not factors or any(value.batch_id not in (None, batch.batch_id) for value in factors):
            raise InvalidMarketData("factors must be non-empty and belong to their batch")
        normalized = tuple(
            AdjustmentFactor(
                value.instrument_id, value.trading_date, value.factor, value.factor_version,
                value.definition, value.available_at, batch.batch_id, value.factor_id,
            ) for value in factors
        )
        event = MarketDataEvent("DatasetBatchPublished", batch.batch_id, datetime.now(timezone.utc), {"kind": "factors"})
        self.repository.save_factors(batch, normalized, event)
        result = self.repository.get_batch(batch.batch_id)
        assert result is not None
        return result

    def create_snapshot(self, batch_ids: Sequence[UUID]) -> DatasetSnapshot:
        ordered = tuple(sorted(set(batch_ids), key=str))
        if not ordered:
            raise InvalidMarketData("snapshot batch set must not be empty")
        for batch_id in ordered:
            batch = self.repository.get_batch(batch_id)
            if batch is None or batch.status is not BatchStatus.PUBLISHED:
                raise InvalidMarketData("snapshot requires published batches")
        digest = hashlib.sha256("\n".join(str(value) for value in ordered).encode()).hexdigest()
        snapshot = DatasetSnapshot(ordered, digest, datetime.now(timezone.utc))
        self.repository.create_snapshot(snapshot)
        return snapshot

    def query_bars(
        self, snapshot_id: UUID, *, instrument_id: UUID | None = None,
        price_mode: PriceMode = PriceMode.RAW, factor_version: str | None = None,
    ) -> tuple[Bar, ...]:
        if self.repository.get_snapshot(snapshot_id) is None:
            raise SnapshotNotFound(str(snapshot_id))
        bars = tuple(
            value for value in self.repository.bars_for_snapshot(snapshot_id)
            if instrument_id is None or value.instrument_id == instrument_id
        )
        bars = tuple(sorted(bars, key=lambda value: (str(value.instrument_id), value.bar_end_at)))
        if price_mode is PriceMode.RAW:
            return bars
        if not factor_version:
            raise FactorUnavailable("adjusted prices require factor_version")
        factors = [value for value in self.repository.factors_for_snapshot(snapshot_id) if value.factor_version == factor_version]
        versions = {value.factor_version for value in self.repository.factors_for_snapshot(snapshot_id)}
        if versions and factor_version not in versions:
            raise FactorUnavailable(f"factor version {factor_version} is absent")
        by_key = {(value.instrument_id, value.trading_date): value for value in factors}
        latest: dict[UUID, Decimal] = {}
        for factor in factors:
            if factor.definition != self.FACTOR_DEFINITION:
                raise FactorUnavailable("factor definition mismatch")
            latest[factor.instrument_id] = max(
                (x for x in factors if x.instrument_id == factor.instrument_id),
                key=lambda x: x.trading_date,
            ).factor
        adjusted: list[Bar] = []
        for bar in bars:
            selected_factor = by_key.get((bar.instrument_id, bar.trading_date))
            if selected_factor is None:
                raise FactorUnavailable(f"factor missing for {bar.instrument_id} on {bar.trading_date}")
            multiplier = selected_factor.factor if price_mode is PriceMode.HFQ else selected_factor.factor / latest[bar.instrument_id]
            adjusted.append(bar.adjusted(multiplier))
        return tuple(adjusted)
