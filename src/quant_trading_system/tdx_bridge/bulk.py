"""Resumable bulk orchestration for TdxQuant historical daily bars."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import Engine, func, or_, select

from quant_trading_system.instruments import (
    AliasInput,
    AssetType,
    Board,
    Exchange,
    InstrumentService,
    LifecycleStatus,
    RegisterInstrumentCommand,
    TradingSpecInput,
)
from quant_trading_system.instruments.sqlalchemy_repository import SqlAlchemyInstrumentRepository
from quant_trading_system.instruments.tables import instrument_aliases
from quant_trading_system.market_data import VolumeUnit
from quant_trading_system.market_data.tables import bars

from .bridge import TdxIngestionBridge
from .client import TdxHttpClient
from .errors import TdxConfigurationError, TdxProtocolError

OVERSEAS_ETF_KEYWORDS = (
    "纳指", "标普", "道琼斯", "美国", "日经", "德国", "法国", "沙特", "印度",
    "越南", "东南亚", "新加坡", "韩国", "亚太", "恒生", "香港", "港股", "中概", "海外",
)


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    symbol: str
    name: str = ""
    asset_type: str = ""

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not normalized or "." not in normalized:
            raise TdxConfigurationError(f"invalid TdxQuant symbol: {self.symbol!r}")
        object.__setattr__(self, "symbol", normalized)
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "asset_type", self.asset_type.strip().upper())


def load_symbol_file(path: Path) -> tuple[SymbolSpec, ...]:
    if not path.is_file():
        raise TdxConfigurationError(f"symbol file does not exist: {path}")
    text = path.read_text(encoding="utf-8-sig")
    first = next((line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")), "")
    result: list[SymbolSpec] = []
    if "," in first and first.lower().split(",", 1)[0].strip() in {"symbol", "code"}:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            symbol = row.get("symbol") or row.get("code") or ""
            if symbol.strip():
                result.append(SymbolSpec(symbol, row.get("name", ""), row.get("asset_type", "")))
    else:
        for line in text.splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                result.append(SymbolSpec(value.split(",", 1)[0]))
    by_symbol: dict[str, SymbolSpec] = {}
    for spec in result:
        by_symbol.setdefault(spec.symbol, spec)
    deduplicated = tuple(by_symbol.values())
    if not deduplicated:
        raise TdxConfigurationError("symbol file contains no symbols")
    return deduplicated


def export_symbol_file(client: TdxHttpClient, markets: Sequence[str], path: Path) -> tuple[SymbolSpec, ...]:
    by_symbol: dict[str, SymbolSpec] = {}
    for market in markets:
        hint = "A_SHARE" if str(market) == "5" else "ETF_AUTO" if str(market) == "31" else ""
        for item in client.get_stock_list(str(market), list_type=1):
            spec = SymbolSpec(item["Code"], item.get("Name", ""), hint)
            previous = by_symbol.get(spec.symbol)
            if previous is None or (not previous.asset_type and spec.asset_type):
                by_symbol[spec.symbol] = spec
    specs = tuple(sorted(by_symbol.values(), key=lambda value: value.symbol))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("symbol", "name", "asset_type"))
    writer.writerows((value.symbol, value.name, value.asset_type) for value in specs)
    _atomic_write(path, output.getvalue())
    return specs


class InstrumentBootstrapper:
    """Register missing canonical instruments from stable TdxQuant reference fields."""

    def __init__(self, engine: Engine, client: TdxHttpClient) -> None:
        self.repository = SqlAlchemyInstrumentRepository(engine)
        self.service = InstrumentService(self.repository)
        self.client = client

    def ensure(self, spec: SymbolSpec) -> bool:
        if self.repository.resolve_aliases("tdx", spec.symbol, date.today()):
            return False
        info = self.client.get_stock_info(spec.symbol)
        list_date = _parse_list_date(info.get("J_start"), spec.symbol)
        if self.repository.resolve_aliases("tdx", spec.symbol, list_date):
            return False
        exchange = _exchange(spec.symbol)
        asset_type, board, classification = _classification(spec, info, exchange)
        unit = _positive_int(info.get("Unit"), default=100)
        tick = _tick_size(info)
        name = str(info.get("Name") or spec.name or spec.symbol).strip()
        stable = {
            "symbol": spec.symbol,
            "name": name,
            "asset_type": asset_type.value,
            "exchange": exchange.value,
            "board": board.value,
            "list_date": list_date.isoformat(),
            "unit": unit,
            "tick_size": str(tick),
            "classification": classification,
        }
        self.service.register(RegisterInstrumentCommand(
            source="tdx",
            source_record_id=spec.symbol,
            revision="tdx-stock-info-v1",
            batch_id="tdx-instrument-bootstrap-v1",
            asset_type=asset_type,
            exchange=exchange,
            board=board,
            currency="CNY",
            name=name,
            list_date=list_date,
            aliases=(AliasInput("tdx", spec.symbol, list_date),),
            trading_specs=(TradingSpecInput(list_date, unit, tick, unit),),
            initial_status=LifecycleStatus.LISTED,
            raw_payload=stable,
        ))
        return True


CoverageReader = Callable[[Sequence[str], date, date], Mapping[str, Mapping[str, Any]]]


class BulkBackfillRunner:
    def __init__(
        self,
        bridge: TdxIngestionBridge,
        bootstrapper: InstrumentBootstrapper,
        coverage_reader: CoverageReader,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bridge = bridge
        self.bootstrapper = bootstrapper
        self.coverage_reader = coverage_reader
        self.sleep = sleep

    def run(
        self,
        specs: Sequence[SymbolSpec],
        *,
        start: date,
        end: date,
        batch_size: int,
        workers: int,
        max_retries: int,
        checkpoint_path: Path,
        report_path: Path,
        volume_unit: VolumeUnit = VolumeUnit.SHARES,
    ) -> Mapping[str, Any]:
        if end < start:
            raise TdxConfigurationError("end date must not precede start date")
        if batch_size < 1 or batch_size > 20:
            raise TdxConfigurationError("batch size must be between 1 and 20")
        if workers < 1 or workers > 8:
            raise TdxConfigurationError("workers must be between 1 and 8")
        if max_retries < 0 or max_retries > 10:
            raise TdxConfigurationError("max retries must be between 0 and 10")
        normalized = tuple(dict.fromkeys(specs))
        fingerprint = _fingerprint(normalized, start, end, volume_unit)
        state = _load_checkpoint(checkpoint_path, fingerprint, len(normalized))
        completed = set(state["completed"])
        failures: dict[str, Mapping[str, Any]] = dict(state["failures"])
        if completed:
            persisted = self.coverage_reader(sorted(completed), start, end)
            stale = sorted(symbol for symbol in completed if symbol not in persisted)
            for symbol in stale:
                completed.remove(symbol)
                failures[symbol] = _failure(
                    TdxProtocolError("checkpoint says completed but no rows are persisted"),
                    failures.get(symbol),
                )
            if stale:
                _save_checkpoint(
                    checkpoint_path, fingerprint, len(normalized), completed, failures
                )
        pending = [value for value in normalized if value.symbol not in completed]
        chunks = [pending[offset:offset + batch_size] for offset in range(0, len(pending), batch_size)]
        state_lock = Lock()
        if workers == 1:
            for candidates in chunks:
                self._process_candidates(
                    candidates, start, end, volume_unit, max_retries,
                    completed, failures, checkpoint_path, fingerprint, len(normalized), state_lock,
                )
                self._print_progress(completed, failures, len(normalized), workers, state_lock)
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tdx-backfill") as pool:
                futures = [
                    pool.submit(
                        self._process_candidates,
                        candidates, start, end, volume_unit, max_retries,
                        completed, failures, checkpoint_path, fingerprint, len(normalized), state_lock,
                    )
                    for candidates in chunks
                ]
                for future in as_completed(futures):
                    future.result()
                    self._print_progress(completed, failures, len(normalized), workers, state_lock)
        coverage = self.coverage_reader([value.symbol for value in normalized], start, end)
        report = {
            "version": 1,
            "fingerprint": fingerprint,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "requested_symbols": len(normalized),
            "completed_symbols": len(completed),
            "failed_symbols": len(failures),
            "coverage_ratio": round(len(completed) / len(normalized), 8),
            "distinct_symbol_dates": sum(int(value["distinct_dates"]) for value in coverage.values()),
            "rows": sum(int(value["rows"]) for value in coverage.values()),
            "coverage": coverage,
            "failures": failures,
        }
        _atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return report

    def _process_candidates(
        self,
        candidates: Sequence[SymbolSpec],
        start: date,
        end: date,
        volume_unit: VolumeUnit,
        max_retries: int,
        completed: set[str],
        failures: dict[str, Mapping[str, Any]],
        checkpoint_path: Path,
        fingerprint: str,
        total: int,
        state_lock: Lock,
    ) -> None:
        ready: list[SymbolSpec] = []
        for spec in candidates:
            try:
                self.bootstrapper.ensure(spec)
                ready.append(spec)
            except Exception as exc:
                self._record_failure(
                    spec.symbol, exc, completed, failures,
                    checkpoint_path, fingerprint, total, state_lock,
                )
        if ready:
            self._ingest_group(
                ready, start, end, volume_unit, max_retries,
                completed, failures, checkpoint_path, fingerprint, total, state_lock,
            )

    @staticmethod
    def _print_progress(
        completed: set[str],
        failures: Mapping[str, Mapping[str, Any]],
        total: int,
        workers: int,
        state_lock: Lock,
    ) -> None:
        with state_lock:
            progress = {
                "event": "bulk_progress",
                "completed": len(completed),
                "failed": len(failures),
                "total": total,
                "workers": workers,
            }
        print(json.dumps(progress, ensure_ascii=False, sort_keys=True), flush=True)

    def _ingest_group(
        self,
        specs: Sequence[SymbolSpec],
        start: date,
        end: date,
        volume_unit: VolumeUnit,
        max_retries: int,
        completed: set[str],
        failures: dict[str, Mapping[str, Any]],
        checkpoint_path: Path,
        fingerprint: str,
        total: int,
        state_lock: Lock,
    ) -> None:
        symbols = [value.symbol for value in specs]
        error = self._attempt(symbols, start, end, volume_unit, max_retries)
        if error is None:
            with state_lock:
                completed.update(symbols)
                for symbol in symbols:
                    failures.pop(symbol, None)
                _save_checkpoint(checkpoint_path, fingerprint, total, completed, failures)
            return
        if len(specs) > 1:
            for spec in specs:
                self._ingest_group(
                    [spec], start, end, volume_unit, max_retries,
                    completed, failures, checkpoint_path, fingerprint, total, state_lock,
                )
            return
        self._record_failure(
            symbols[0], error, completed, failures,
            checkpoint_path, fingerprint, total, state_lock,
        )

    @staticmethod
    def _record_failure(
        symbol: str,
        error: Exception,
        completed: set[str],
        failures: dict[str, Mapping[str, Any]],
        checkpoint_path: Path,
        fingerprint: str,
        total: int,
        state_lock: Lock,
    ) -> None:
        with state_lock:
            failures[symbol] = _failure(error, failures.get(symbol))
            _save_checkpoint(checkpoint_path, fingerprint, total, completed, failures)

    def _attempt(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        volume_unit: VolumeUnit,
        max_retries: int,
    ) -> Exception | None:
        for attempt in range(max_retries + 1):
            try:
                self.bridge.backfill(symbols, start=start, end=end, volume_unit=volume_unit)
                return None
            except Exception as exc:
                if attempt == max_retries:
                    return exc
                self.sleep(min(2 ** attempt, 8))
        raise AssertionError("retry loop did not return")


def sqlalchemy_coverage_reader(engine: Engine) -> CoverageReader:
    def read(symbols: Sequence[str], start: date, end: date) -> Mapping[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for offset in range(0, len(symbols), 500):
            chunk = symbols[offset:offset + 500]
            statement = (
                select(
                    instrument_aliases.c.code,
                    func.count(func.distinct(bars.c.trading_date)),
                    func.count(),
                    func.min(bars.c.trading_date),
                    func.max(bars.c.trading_date),
                )
                .select_from(bars.join(instrument_aliases, bars.c.instrument_id == instrument_aliases.c.instrument_id))
                .where(
                    instrument_aliases.c.source == "tdx",
                    instrument_aliases.c.code.in_(chunk),
                    bars.c.frequency == "1d",
                    bars.c.trading_date >= start,
                    bars.c.trading_date <= end,
                    instrument_aliases.c.valid_from <= bars.c.trading_date,
                    or_(instrument_aliases.c.valid_to.is_(None), instrument_aliases.c.valid_to > bars.c.trading_date),
                )
                .group_by(instrument_aliases.c.code)
            )
            with engine.connect() as connection:
                rows = connection.execute(statement).all()
            for symbol, dates, row_count, earliest, latest in rows:
                result[str(symbol)] = {
                    "distinct_dates": int(dates),
                    "rows": int(row_count),
                    "earliest": earliest.isoformat(),
                    "latest": latest.isoformat(),
                }
        return result
    return read


def _classification(
    spec: SymbolSpec, info: Mapping[str, Any], exchange: Exchange
) -> tuple[AssetType, Board, str]:
    kind = str(info.get("HSStockKind", "")).strip()
    if spec.asset_type.startswith("ETF") or kind == "7":
        if exchange not in {Exchange.SSE, Exchange.SZSE}:
            raise TdxProtocolError(f"ETF is not on SSE/SZSE: {spec.symbol}")
        if spec.asset_type in {AssetType.ETF_DOMESTIC.value, AssetType.ETF_OVERSEAS_LINKED.value}:
            asset_type = AssetType(spec.asset_type)
            method = "symbol-file"
        else:
            name = str(info.get("Name") or spec.name)
            overseas = any(keyword in name for keyword in OVERSEAS_ETF_KEYWORDS)
            asset_type = AssetType.ETF_OVERSEAS_LINKED if overseas else AssetType.ETF_DOMESTIC
            method = "tdx-name-keyword-v1"
        return asset_type, Board.ETF, method
    boards = {
        "1": Board.SH_MAIN if exchange is Exchange.SSE else Board.SZ_MAIN,
        "2": Board.BSE,
        "3": Board.CHINEXT,
        "4": Board.STAR,
    }
    board = boards.get(kind)
    if board is None:
        raise TdxProtocolError(f"unsupported HSStockKind={kind!r} for {spec.symbol}")
    return AssetType.A_SHARE, board, "tdx-HSStockKind"


def _exchange(symbol: str) -> Exchange:
    suffix = symbol.rsplit(".", 1)[1]
    mapping = {"SH": Exchange.SSE, "SZ": Exchange.SZSE, "BJ": Exchange.BSE}
    try:
        return mapping[suffix]
    except KeyError as exc:
        raise TdxProtocolError(f"unsupported exchange suffix for {symbol}") from exc


def _parse_list_date(value: Any, symbol: str) -> date:
    text = str(value or "").strip().split(".", 1)[0]
    if len(text) != 8 or not text.isdigit() or text == "00000000":
        raise TdxProtocolError(f"missing listing date for {symbol}")
    try:
        return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:]}")
    except ValueError as exc:
        raise TdxProtocolError(f"invalid listing date for {symbol}: {value}") from exc


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return default
    return parsed if parsed > 0 else default


def _tick_size(info: Mapping[str, Any]) -> Decimal:
    try:
        value = Decimal(str(info.get("MinPrice", "0")))
    except InvalidOperation:
        value = Decimal(0)
    if value > 0:
        return value
    decimals = _positive_int(info.get("XsFlag"), default=3)
    return Decimal(1).scaleb(-decimals)


def _fingerprint(specs: Sequence[SymbolSpec], start: date, end: date, unit: VolumeUnit) -> str:
    payload = {
        "symbols": [value.symbol for value in specs],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "volume_unit": unit.value,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _load_checkpoint(path: Path, fingerprint: str, total: int) -> Mapping[str, Any]:
    if not path.exists():
        return {"completed": [], "failures": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TdxConfigurationError(f"cannot read checkpoint: {path}") from exc
    if state.get("fingerprint") != fingerprint or state.get("total") != total:
        raise TdxConfigurationError("checkpoint belongs to a different symbol set or date range")
    if not isinstance(state.get("completed"), list) or not isinstance(state.get("failures"), dict):
        raise TdxConfigurationError("checkpoint has an invalid shape")
    return state


def _save_checkpoint(
    path: Path,
    fingerprint: str,
    total: int,
    completed: set[str],
    failures: Mapping[str, Mapping[str, Any]],
) -> None:
    payload = {
        "version": 1,
        "fingerprint": fingerprint,
        "total": total,
        "completed": sorted(completed),
        "failures": failures,
    }
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _failure(exc: Exception, previous: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return {
        "attempts": int((previous or {}).get("attempts", 0)) + 1,
        "error_type": type(exc).__name__,
        "message": str(exc)[:1000],
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
