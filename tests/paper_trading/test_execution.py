from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from paper_trading.config import commission, dividend_tax_rate, stamp_duty_rate
from paper_trading.execution import execute_pending_plan, process_dividends, run_day
from paper_trading.market import DataStore
from paper_trading.models import Book, Lot, PaperState, PendingPlan
from paper_trading.state import StateRepository


def _write(root: Path, name: str, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(root / name, index=False)


def test_dated_cost_and_tax_rules() -> None:
    assert commission(1_000.0) == 5.0
    assert commission(100_000.0) == 12.0
    assert stamp_duty_rate("2023-08-27") == pytest.approx(0.001)
    assert stamp_duty_rate("2023-08-28") == pytest.approx(0.0005)
    assert dividend_tax_rate(30) == 0.20
    assert dividend_tax_rate(31) == 0.10
    assert dividend_tax_rate(366) == 0.0


def test_exchange_calendar_month_end_not_calendar_month_end(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "calendar.parquet",
        [
            {"exchange": "SSE", "cal_date": "20260529", "is_open": 1},
            {"exchange": "SSE", "cal_date": "20260601", "is_open": 1},
        ],
    )
    store = DataStore(tmp_path)
    assert store.is_last_trading_day_of_month("2026-05-29") is True
    assert store.next_trading_day("2026-05-29") == "2026-06-01"


def test_missing_open_never_deletes_position() -> None:
    book = Book("dividend", 0.0, lots={"AAA": [Lot.new(100, "2026-01-01", 10.0)]})
    book.pending_plan = PendingPlan("p1", "dividend", "2026-08-18", "2026-08-19", {}, reason="exit")
    result = execute_pending_plan(book, "2026-08-19", {})
    assert result["status"] == "BLOCKED"
    assert book.holdings == {"AAA": 100}
    assert book.pending_plan is not None


def test_rebalance_sells_and_buys_retained_target_weights() -> None:
    book = Book("voltrend", 1_100.0, lots={"AAA": [Lot.new(100, "2026-01-01", 10.0)]})
    book.pending_plan = PendingPlan(
        "p2",
        "voltrend",
        "2026-08-18",
        "2026-08-19",
        {"AAA": 0.5, "BBB": 0.5},
        reason="rebalance",
    )
    result = execute_pending_plan(book, "2026-08-19", {"AAA": 10.0, "BBB": 10.0})
    assert result["status"] == "FILLED"
    assert book.holdings == {"AAA": 100, "BBB": 100}
    assert len(book.fills) == 1
    assert book.fills[0].side == "BUY"


def test_zero_target_actually_moves_vol_book_to_cash() -> None:
    book = Book("voltrend", 0.0, lots={"AAA": [Lot.new(100, "2025-01-01", 10.0)]})
    book.pending_plan = PendingPlan("p3", "voltrend", "2026-08-18", "2026-08-19", {}, reason="risk")
    result = execute_pending_plan(book, "2026-08-19", {"AAA": 10.0})
    assert result["status"] == "FILLED"
    assert book.holdings == {}
    assert book.cash == pytest.approx(994.5)


def test_dividend_is_entitled_on_record_date_paid_on_pay_date_and_taxed_on_sale() -> None:
    book = Book("dividend", 0.0, lots={"AAA": [Lot.new(100, "2026-08-01", 10.0)]})
    actions = pd.DataFrame(
        [{"ts_code": "AAA", "record_date": "20260819", "pay_date": "20260820", "ex_date": "20260820", "cash_div": 0.5}]
    )
    reinvest, warnings = process_dividends(book, "2026-08-19", actions)
    assert reinvest == {}
    assert warnings == []
    assert book.cash == 0.0
    reinvest, warnings = process_dividends(book, "2026-08-20", actions)
    assert reinvest == {"AAA": 50.0}
    assert warnings == []
    assert book.cash == 50.0
    book.pending_plan = PendingPlan("p4", "dividend", "2026-08-20", "2026-08-21", {}, reason="sell")
    result = execute_pending_plan(book, "2026-08-21", {"AAA": 10.0})
    fill = result["fills"][0]
    assert fill["dividend_tax"] == pytest.approx(10.0)
    assert book.cash == pytest.approx(1_034.5)


def test_legacy_state_is_preserved_but_marked_unverified(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "start_date": "20260817",
                "dividend_book": {"name": "d", "cash": 100.0, "holdings": {"AAA": 100}, "nav_history": []},
                "voltrend_book": {"name": "v", "cash": 200.0, "holdings": {}, "nav_history": []},
            }
        ),
        encoding="utf-8",
    )
    state = StateRepository(path).load()
    assert state.legacy_import is True
    assert state.dividend_book.holdings == {"AAA": 100}
    assert state.start_date == "2026-08-17"
    blocked = run_day(state, DataStore(tmp_path), "2026-08-19")
    assert blocked == {"date": "2026-08-19", "status": "BLOCKED", "errors": ["legacy_state_requires_reset_or_verified_import"]}


def test_run_day_queues_next_open_instead_of_same_close_fill(tmp_path: Path) -> None:
    dates = pd.date_range("2026-08-17", periods=11, freq="B")
    calendar = [
        {"exchange": "SSE", "cal_date": value.strftime("%Y%m%d"), "is_open": 1}
        for value in dates
    ]
    quotes = []
    for value in dates:
        quotes.append({"ts_code": "AAA.SH", "trade_date": value, "open": 10.0, "close": 10.0, "amount": 10_000.0})
    _write(tmp_path, "calendar.parquet", calendar)
    _write(tmp_path, "quotes.parquet", quotes)
    _write(
        tmp_path,
        "valuation.parquet",
        [{"ts_code": "AAA.SH", "trade_date": dates[-2], "pe_ttm": 10.0, "dv_ttm": 6.0}],
    )
    _write(
        tmp_path,
        "stock_basic.parquet",
        [{"ts_code": "AAA.SH", "name": "AAA", "market": "主板", "list_date": "20200101", "list_status": "L"}],
    )
    _write(tmp_path, "dividend.parquet", [{"ts_code": "ZZZ", "record_date": "20260101", "pay_date": "20260102", "cash_div": 0.1}])
    state = PaperState()
    result = run_day(state, DataStore(tmp_path), dates[-2].strftime("%Y-%m-%d"))
    assert result["status"] == "COMPLETE"
    assert state.dividend_book.holdings == {}
    assert state.dividend_book.pending_plan is not None
    assert state.dividend_book.pending_plan.execute_date == dates[-1].strftime("%Y-%m-%d")



def test_realistic_rebalance_sells_at_open_and_buys_at_open_close_average() -> None:
    book = Book(
        "voltrend",
        100.0,
        lots={"AAA": [Lot.new(100, "2026-01-01", 10.0)]},
    )
    book.pending_plan = PendingPlan(
        "p5",
        "voltrend",
        "2026-08-18",
        "2026-08-19",
        {"BBB": 1.0},
        reason="rebalance",
    )
    result = execute_pending_plan(
        book,
        "2026-08-19",
        {"AAA": 10.0, "BBB": 8.0},
        {"AAA": 10.0, "BBB": 12.0},
        {"AAA": 11.0, "BBB": 13.2},
    )
    assert result["status"] == "FILLED"
    assert result["sell_price_policy"] == "open"
    assert result["buy_price_policy"] == "open_close_average"
    assert [(fill.side, fill.price) for fill in book.fills] == [
        ("SELL", 10.0),
        ("BUY", 10.0),
    ]
    assert book.holdings == {"BBB": 100}


def test_realistic_rebalance_skips_close_at_official_limit_up() -> None:
    book = Book("voltrend", 1_100.0)
    book.pending_plan = PendingPlan(
        "p6",
        "voltrend",
        "2026-08-18",
        "2026-08-19",
        {"BBB": 1.0},
        reason="rebalance",
    )
    result = execute_pending_plan(
        book,
        "2026-08-19",
        {"BBB": 10.0},
        {"BBB": 11.0},
        {"BBB": 11.0},
    )
    assert result["status"] == "PARTIAL"
    assert result["fills"] == []
    assert result["warnings"] == ["limit_up_buy_skipped:BBB"]
    assert book.cash == 1_100.0


def test_realistic_rebalance_blocks_before_trading_when_limit_price_is_missing() -> None:
    book = Book("voltrend", 1_100.0)
    book.pending_plan = PendingPlan(
        "p7", "voltrend", "2026-08-18", "2026-08-19", {"BBB": 1.0}
    )
    result = execute_pending_plan(
        book, "2026-08-19", {"BBB": 10.0}, {"BBB": 10.0}, {}
    )
    assert result["status"] == "BLOCKED"
    assert result["fills"] == []
    assert book.pending_plan is not None

