from __future__ import annotations

from pathlib import Path

import pandas as pd

from paper_trading.market import DataStore
from paper_trading.models import Lot, PaperState
from paper_trading.monitoring import health_status, reconcile, record_alerts


def test_reconciliation_detects_and_then_clears_cash_and_holding_differences() -> None:
    state = PaperState()
    state.dividend_book.cash = 100.0
    state.dividend_book.lots = {"AAA": [Lot.new(100, "2026-08-01", 10.0)]}
    failed = reconcile(
        state,
        "2026-08-19",
        {"cash": 99.0, "holdings": {"AAA": 0}},
        {"cash": state.voltrend_book.cash, "holdings": {}},
    )
    assert failed["status"] == "FAIL"
    assert failed["dividend"]["holding_differences"]["AAA"] == {"expected": 100, "actual": 0}
    passed = reconcile(
        state,
        "2026-08-19",
        {"cash": 100.0, "holdings": {"AAA": 100}},
        {"cash": state.voltrend_book.cash, "holdings": {}},
    )
    assert passed["status"] == "PASS"
    assert len(state.reconciliations) == 1


def test_shadow_acceptance_requires_60_days_three_month_ends_and_reconciliation(tmp_path: Path) -> None:
    state = PaperState()
    dates = pd.date_range("2026-01-02", periods=60, freq="B")
    for index, value in enumerate(dates):
        trade_date = value.strftime("%Y-%m-%d")
        state.run_history.append(
            {"date": trade_date, "status": "COMPLETE", "month_end": index in (19, 39, 59)}
        )
        state.reconciliations.append({"date": trade_date, "status": "PASS"})
    status = health_status(state, DataStore(tmp_path), dates[-1].strftime("%Y-%m-%d"))
    assert status["status"] == "READY"
    assert status["acceptance"]["observed_shadow_days"] == 60
    assert status["acceptance"]["observed_month_end_cycles"] == 3
    assert status["live_order_submission"] is False


def test_missing_daily_run_is_critical_and_alert_history_is_idempotent(tmp_path: Path) -> None:
    state = PaperState()
    status = health_status(state, DataStore(tmp_path), "2026-08-19")
    assert status["status"] == "BLOCKED"
    assert {alert["code"] for alert in status["alerts"]} >= {
        "DAILY_RUN_MISSING",
        "RECONCILIATION_MISSING",
    }
    record_alerts(state, status)
    record_alerts(state, status)
    assert len(state.alerts) == len(status["alerts"])
