from __future__ import annotations

from pathlib import Path

import pandas as pd

import paper_trading.strategies as strategies
from paper_trading.execution import run_day
from paper_trading.market import DataStore
from paper_trading.models import PaperState


def test_execution_blocks_closed_calendar_day(tmp_path: Path) -> None:
    pd.DataFrame(
        [{"exchange": "SSE", "cal_date": "20260819", "is_open": 1}]
    ).to_parquet(tmp_path / "calendar.parquet", index=False)
    state = PaperState()
    result = run_day(state, DataStore(tmp_path), "2026-08-20")
    assert result == {
        "date": "2026-08-20",
        "status": "BLOCKED",
        "errors": ["not_an_open_trading_day"],
    }


def test_daily_scan_can_trigger_position_without_constituent_rebalance(monkeypatch) -> None:
    class StubStore:
        def read(self, name: str) -> pd.DataFrame:
            if name == "stock_basic.parquet":
                return pd.DataFrame({"ts_code": ["AAA"], "name": ["甲"]})
            return pd.DataFrame()

        def prices(self, trade_date: str, field: str) -> dict[str, float]:
            return {}

        def calendar(self) -> pd.DatetimeIndex:
            return pd.DatetimeIndex(["2026-08-19", "2026-08-20"])

        def is_last_trading_day_of_month(self, trade_date: str) -> bool:
            return False

        def next_trading_day(self, trade_date: str) -> str:
            return "2026-08-20"

    monkeypatch.setattr(strategies, "dividend_weights", lambda store, date: {"AAA": 1.0})
    monkeypatch.setattr(strategies, "balanced_weights", lambda store, date: {"AAA": 1.0})
    monkeypatch.setattr(strategies, "voltrend_target_position", lambda book, nav, date: 0.8)
    state = PaperState()
    state.dividend_book.model_weights = {"AAA": 1.0}
    state.voltrend_book.model_weights = {"AAA": 1.0}
    state.voltrend_book.risk_position = 1.0

    result = strategies.scan(state, StubStore(), "2026-08-19")

    assert result["execution_triggers"]["dividend_constituents"]["due"] is False
    assert result["execution_triggers"]["voltrend_constituents"]["due"] is False
    assert result["execution_triggers"]["voltrend_position"]["due"] is True
    assert result["signal_status"] == "REBALANCE_DUE"
    assert result["execution_policy"]["scan"] == "daily"
