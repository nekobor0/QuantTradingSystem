from __future__ import annotations

from pathlib import Path

import pandas as pd

from paper_trading.market import DataStore
from paper_trading.models import Lot, PaperState
from paper_trading.monitoring import health_status, reconcile, record_alerts


def _snapshots(state: PaperState) -> dict:
    return {
        key: {
            "dividend": {
                "cash": strategy.dividend_book.cash,
                "holdings": strategy.dividend_book.holdings,
            },
            "voltrend": {
                "cash": strategy.voltrend_book.cash,
                "holdings": strategy.voltrend_book.holdings,
            },
        }
        for key, strategy in state.strategies.items()
    }


def test_reconciliation_fails_if_any_ab_book_differs_and_then_passes() -> None:
    state = PaperState()
    state.strategies["A"].dividend_book.cash = 100.0
    state.strategies["A"].dividend_book.lots = {
        "AAA": [Lot.new(100, "2026-08-01", 10.0)]
    }
    snapshots = _snapshots(state)
    snapshots["A"]["dividend"] = {"cash": 99.0, "holdings": {"AAA": 0}}
    failed = reconcile(state, "2026-08-19", snapshots)
    assert failed["status"] == "FAIL"
    assert failed["strategies"]["A"]["dividend"]["holding_differences"]["AAA"] == {
        "expected": 100,
        "actual": 0,
    }
    passed = reconcile(state, "2026-08-19", _snapshots(state))
    assert passed["status"] == "PASS"
    assert len(state.reconciliations) == 1


def test_reconciliation_rejects_missing_strategy_snapshot() -> None:
    state = PaperState()
    snapshots = _snapshots(state)
    snapshots.pop("B")
    try:
        reconcile(state, "2026-08-19", snapshots)
    except ValueError as exc:
        assert "missing strategy snapshots: B" in str(exc)
    else:
        raise AssertionError("missing B snapshot should fail")


def test_shadow_acceptance_requires_60_days_three_month_ends_and_ab_reconciliation(
    tmp_path: Path,
) -> None:
    state = PaperState()
    dates = pd.date_range("2026-01-02", periods=60, freq="B")
    for index, value in enumerate(dates):
        trade_date = value.strftime("%Y-%m-%d")
        state.run_history.append(
            {
                "date": trade_date,
                "status": "COMPLETE",
                "month_end": index in (19, 39, 59),
                "strategies": {"A": {"risk_status": "NORMAL"}, "B": {"risk_status": "NORMAL"}},
            }
        )
        state.reconciliations.append(
            {
                "date": trade_date,
                "status": "PASS",
                "strategies": {"A": {"status": "PASS"}, "B": {"status": "PASS"}},
            }
        )
    status = health_status(state, DataStore(tmp_path), dates[-1].strftime("%Y-%m-%d"))
    assert status["status"] == "READY"
    assert set(status["strategies"]) == {"A", "B"}
    assert status["acceptance"]["observed_shadow_days"] == 60
    assert status["acceptance"]["observed_month_end_cycles"] == 3


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
