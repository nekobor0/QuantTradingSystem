"""P2 paper-only reconciliation, health checks, alerts, and acceptance gates."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .market import DataStore
from .models import Book, PaperState

MIN_SHADOW_DAYS = 60
MIN_MONTH_END_CYCLES = 3
MIN_RECONCILIATION_COVERAGE = 0.95
MIN_RECONCILIATION_PASS_RATE = 0.99


def _book_diff(book: Book, snapshot: dict[str, Any], cash_tolerance: float) -> dict[str, Any]:
    actual = {str(symbol): int(shares) for symbol, shares in snapshot.get("holdings", {}).items() if int(shares) != 0}
    expected = book.holdings
    symbols = sorted(set(expected).union(actual))
    holding_differences = {
        symbol: {"expected": expected.get(symbol, 0), "actual": actual.get(symbol, 0)}
        for symbol in symbols
        if expected.get(symbol, 0) != actual.get(symbol, 0)
    }
    actual_cash = float(snapshot.get("cash", 0.0))
    cash_difference = actual_cash - book.cash
    return {
        "expected_cash": round(book.cash, 2),
        "actual_cash": round(actual_cash, 2),
        "cash_difference": round(cash_difference, 2),
        "holding_differences": holding_differences,
        "passed": not holding_differences and abs(cash_difference) <= cash_tolerance,
    }


def reconcile(
    state: PaperState,
    trade_date: str,
    dividend_snapshot: dict[str, Any],
    voltrend_snapshot: dict[str, Any],
    source: str = "manual_snapshot",
    cash_tolerance: float = 1.0,
) -> dict[str, Any]:
    date_value = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    dividend = _book_diff(state.dividend_book, dividend_snapshot, cash_tolerance)
    voltrend = _book_diff(state.voltrend_book, voltrend_snapshot, cash_tolerance)
    record = {
        "date": date_value,
        "source": source,
        "status": "PASS" if dividend["passed"] and voltrend["passed"] else "FAIL",
        "dividend": dividend,
        "voltrend": voltrend,
    }
    state.reconciliations = [row for row in state.reconciliations if row.get("date") != date_value]
    state.reconciliations.append(record)
    return record


def health_status(state: PaperState, store: DataStore, effective_date: str) -> dict[str, Any]:
    effective = pd.Timestamp(effective_date).strftime("%Y-%m-%d")
    complete_runs = [row for row in state.run_history if row.get("status") == "COMPLETE"]
    observed_dates = sorted({str(row.get("date")) for row in complete_runs if row.get("date")})
    reconciled_dates = {str(row.get("date")) for row in state.reconciliations if row.get("date")}
    passed_reconciliations = [row for row in state.reconciliations if row.get("status") == "PASS"]
    month_end_cycles = sum(bool(row.get("month_end")) for row in complete_runs)
    alerts: list[dict[str, str]] = []
    if state.legacy_import:
        alerts.append({"severity": "CRITICAL", "code": "LEGACY_STATE", "message": "旧版合成持仓尚未重置或核验"})
    if effective not in observed_dates:
        alerts.append({"severity": "CRITICAL", "code": "DAILY_RUN_MISSING", "message": f"{effective} 尚无 COMPLETE 运行"})
    for book in (state.dividend_book, state.voltrend_book):
        plan = book.pending_plan
        if plan and plan.status == "PENDING" and plan.execute_date and plan.execute_date < effective:
            alerts.append({"severity": "CRITICAL", "code": "PLAN_OVERDUE", "message": f"{book.name} 计划 {plan.plan_id} 已逾期"})
    calendar = store.calendar()
    if len(calendar) and calendar[-1].strftime("%Y-%m-%d") < effective:
        alerts.append({"severity": "CRITICAL", "code": "MARKET_DATA_STALE", "message": "行情日历早于有效交易日"})
    latest_reconciliation = next((row for row in reversed(state.reconciliations) if row.get("date") == effective), None)
    if latest_reconciliation is None:
        alerts.append({"severity": "WARNING", "code": "RECONCILIATION_MISSING", "message": f"{effective} 尚未导入外部模拟仓快照"})
    elif latest_reconciliation.get("status") != "PASS":
        alerts.append({"severity": "CRITICAL", "code": "RECONCILIATION_FAILED", "message": f"{effective} 持仓或现金对账失败"})
    coverage = len(reconciled_dates.intersection(observed_dates)) / len(observed_dates) if observed_dates else 0.0
    pass_rate = len(passed_reconciliations) / len(state.reconciliations) if state.reconciliations else 0.0
    acceptance = {
        "minimum_shadow_days": MIN_SHADOW_DAYS,
        "observed_shadow_days": len(observed_dates),
        "minimum_month_end_cycles": MIN_MONTH_END_CYCLES,
        "observed_month_end_cycles": month_end_cycles,
        "minimum_reconciliation_coverage": MIN_RECONCILIATION_COVERAGE,
        "reconciliation_coverage": round(coverage, 6),
        "minimum_reconciliation_pass_rate": MIN_RECONCILIATION_PASS_RATE,
        "reconciliation_pass_rate": round(pass_rate, 6),
    }
    ready = (
        len(observed_dates) >= MIN_SHADOW_DAYS
        and month_end_cycles >= MIN_MONTH_END_CYCLES
        and coverage >= MIN_RECONCILIATION_COVERAGE
        and pass_rate >= MIN_RECONCILIATION_PASS_RATE
        and not any(alert["severity"] == "CRITICAL" for alert in alerts)
    )
    return {
        "as_of": effective,
        "mode": "PAPER_SHADOW_ONLY",
        "status": "READY" if ready else "BLOCKED" if any(a["severity"] == "CRITICAL" for a in alerts) else "COLLECTING",
        "acceptance": acceptance,
        "alerts": alerts,
        "latest_reconciliation": latest_reconciliation,
        "live_order_submission": False,
    }


def record_alerts(state: PaperState, status: dict[str, Any]) -> None:
    as_of = str(status["as_of"])
    existing = {(row.get("date"), row.get("code")) for row in state.alerts}
    for alert in status["alerts"]:
        key = (as_of, alert["code"])
        if key not in existing:
            state.alerts.append({"date": as_of, **alert})
            existing.add(key)
    state.alerts = state.alerts[-500:]
