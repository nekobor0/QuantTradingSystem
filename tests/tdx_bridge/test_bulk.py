from __future__ import annotations

import csv
import json
from datetime import date
from threading import Barrier, Lock, get_ident

from quant_trading_system.market_data import VolumeUnit
from quant_trading_system.tdx_bridge.bulk import (
    BulkBackfillRunner,
    SymbolSpec,
    export_symbol_file,
    load_symbol_file,
)


class FakeBootstrapper:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    def ensure(self, spec: SymbolSpec) -> bool:
        self.symbols.append(spec.symbol)
        return True


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.b_failures = 0

    def backfill(self, symbols, *, start, end, volume_unit):
        assert start == date(2024, 1, 1)
        assert end == date(2024, 1, 31)
        assert volume_unit is VolumeUnit.SHARES
        normalized = tuple(symbols)
        self.calls.append(normalized)
        if len(normalized) > 1 and "000002.SZ" in normalized:
            raise RuntimeError("split this batch")
        if normalized == ("000002.SZ",) and self.b_failures == 0:
            self.b_failures += 1
            raise RuntimeError("retry once")
        return object()


def coverage(symbols, _start, _end):
    return {
        symbol: {"distinct_dates": 22, "rows": 22, "earliest": "2024-01-02", "latest": "2024-01-31"}
        for symbol in symbols
    }


def test_symbol_file_supports_csv_comments_and_deduplication(tmp_path) -> None:
    path = tmp_path / "symbols.csv"
    path.write_text(
        "symbol,name,asset_type\n600000.SH,浦发银行,A_SHARE\n600000.sh,重复,A_SHARE\n510300.SH,ETF,ETF_DOMESTIC\n",
        encoding="utf-8",
    )
    assert [value.symbol for value in load_symbol_file(path)] == ["600000.SH", "510300.SH"]


def test_export_symbol_file_merges_markets(tmp_path) -> None:
    class Client:
        def get_stock_list(self, market, *, list_type):
            assert list_type == 1
            if market == "5":
                return ({"Code": "600000.SH", "Name": "浦发银行"},)
            return ({"Code": "510300.SH", "Name": "沪深300ETF"},)

    path = tmp_path / "universe.csv"
    specs = export_symbol_file(Client(), ["5", "31"], path)
    assert [value.asset_type for value in specs] == ["ETF_AUTO", "A_SHARE"]
    with path.open(encoding="utf-8", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 2


def test_bulk_backfill_retries_splits_checkpoints_and_resumes(tmp_path) -> None:
    bridge = FakeBridge()
    bootstrapper = FakeBootstrapper()
    runner = BulkBackfillRunner(bridge, bootstrapper, coverage, sleep=lambda _seconds: None)
    specs = tuple(SymbolSpec(value) for value in ("000001.SZ", "000002.SZ", "600000.SH"))
    checkpoint = tmp_path / "checkpoint.json"
    report_path = tmp_path / "report.json"

    report = runner.run(
        specs,
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        batch_size=2,
        workers=1,
        max_retries=1,
        checkpoint_path=checkpoint,
        report_path=report_path,
    )

    assert report["completed_symbols"] == 3
    assert report["failed_symbols"] == 0
    assert report["distinct_symbol_dates"] == 66
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["completed"] == [
        "000001.SZ", "000002.SZ", "600000.SH"
    ]
    first_calls = list(bridge.calls)
    runner.run(
        specs,
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        batch_size=2,
        workers=1,
        max_retries=1,
        checkpoint_path=checkpoint,
        report_path=report_path,
    )
    assert bridge.calls == first_calls


def test_bulk_backfill_runs_independent_batches_in_parallel(tmp_path) -> None:
    barrier = Barrier(2)
    call_lock = Lock()
    thread_ids: set[int] = set()

    class ParallelBridge:
        def backfill(self, symbols, *, start, end, volume_unit):
            with call_lock:
                thread_ids.add(get_ident())
            barrier.wait(timeout=2)
            return object()

    specs = (SymbolSpec("000001.SZ"), SymbolSpec("600000.SH"))
    report = BulkBackfillRunner(ParallelBridge(), FakeBootstrapper(), coverage).run(
        specs,
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        batch_size=1,
        workers=2,
        max_retries=0,
        checkpoint_path=tmp_path / "checkpoint.json",
        report_path=tmp_path / "report.json",
    )

    assert len(thread_ids) == 2
    assert report["completed_symbols"] == 2


def test_bulk_backfill_retries_checkpoint_completion_without_persisted_rows(tmp_path) -> None:
    bridge = FakeBridge()
    runner = BulkBackfillRunner(
        bridge,
        FakeBootstrapper(),
        lambda _symbols, _start, _end: {},
        sleep=lambda _seconds: None,
    )
    specs = (SymbolSpec("600000.SH"),)
    checkpoint = tmp_path / "checkpoint.json"
    arguments = {
        "start": date(2024, 1, 1),
        "end": date(2024, 1, 31),
        "batch_size": 1,
        "workers": 1,
        "max_retries": 0,
        "checkpoint_path": checkpoint,
        "report_path": tmp_path / "report.json",
    }

    runner.run(specs, **arguments)
    runner.run(specs, **arguments)

    assert bridge.calls == [("600000.SH",), ("600000.SH",)]
