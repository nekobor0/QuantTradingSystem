"""Paper-only next-open execution, accounting, corporate-action, and risk engine."""

from __future__ import annotations

from datetime import date
from math import floor
from uuid import uuid4

import numpy as np
import pandas as pd

from .config import (
    BUY_LOT,
    MA_N,
    RISK_ALERT_DRAWDOWN,
    RISK_HARD_ACTION,
    RISK_HARD_DRAWDOWN,
    TARGET_VOL,
    VOL_WINDOW,
    commission,
    dividend_tax_rate,
    stamp_duty_rate,
)
from .market import DataStore, balanced_weights, dividend_weights
from .models import Book, CashEvent, DividendEntitlement, Fill, Lot, PaperState, PendingPlan


def book_nav(book: Book, prices: dict[str, float]) -> tuple[float, list[str]]:
    warnings: list[str] = []
    value = book.cash
    for symbol, shares in book.holdings.items():
        price = prices.get(symbol) or book.last_prices.get(symbol)
        if price is None or price <= 0:
            warnings.append(f"missing_mark:{symbol}")
            continue
        value += shares * price
    return value, warnings


def _sell_fifo(book: Book, plan_id: str, symbol: str, shares: int, price: float, trade_date: str) -> Fill | None:
    shares = min(shares, book.shares(symbol))
    if shares <= 0 or price <= 0:
        return None
    remaining = shares
    dividend_tax = 0.0
    kept: list[Lot] = []
    for lot in book.lots.get(symbol, []):
        if remaining <= 0:
            kept.append(lot)
            continue
        sold = min(lot.shares, remaining)
        held_days = (date.fromisoformat(trade_date) - date.fromisoformat(lot.acquired_date)).days
        dividend_tax += sold * lot.taxable_dividend_per_share * dividend_tax_rate(held_days)
        lot.shares -= sold
        remaining -= sold
        if lot.shares > 0:
            kept.append(lot)
    if kept:
        book.lots[symbol] = kept
    else:
        book.lots.pop(symbol, None)
    notional = shares * price
    fee = commission(notional)
    stamp = notional * stamp_duty_rate(trade_date)
    book.cash += notional - fee - stamp - dividend_tax
    fill = Fill(uuid4().hex, plan_id, trade_date, symbol, "SELL", shares, price, fee, stamp, dividend_tax)
    book.fills.append(fill)
    return fill


def _buy(book: Book, plan_id: str, symbol: str, requested_shares: int, price: float, trade_date: str) -> Fill | None:
    requested_shares = floor(requested_shares / BUY_LOT) * BUY_LOT
    if requested_shares <= 0 or price <= 0:
        return None
    shares = requested_shares
    while shares > 0 and shares * price + commission(shares * price) > book.cash:
        shares -= BUY_LOT
    if shares <= 0:
        return None
    notional = shares * price
    fee = commission(notional)
    book.cash -= notional + fee
    book.lots.setdefault(symbol, []).append(Lot.new(shares, trade_date, (notional + fee) / shares))
    fill = Fill(uuid4().hex, plan_id, trade_date, symbol, "BUY", shares, price, fee, 0.0, 0.0)
    book.fills.append(fill)
    return fill


def execute_pending_plan(book: Book, trade_date: str, open_prices: dict[str, float]) -> dict:
    plan = book.pending_plan
    if plan is None or plan.status != "PENDING" or plan.execute_date != trade_date:
        return {"status": "NO_PLAN", "fills": [], "warnings": []}
    missing_held = sorted(symbol for symbol in book.holdings if symbol not in open_prices)
    if missing_held:
        plan.warnings.append("missing_open_for_held:" + ",".join(missing_held))
        return {"status": "BLOCKED", "fills": [], "warnings": list(plan.warnings)}
    nav, _ = book_nav(book, open_prices)
    targets = {symbol: max(0.0, float(weight)) for symbol, weight in plan.target_weights.items()}
    if sum(targets.values()) > 1.000001:
        plan.status = "REJECTED"
        plan.warnings.append("target_weights_exceed_one")
        return {"status": "REJECTED", "fills": [], "warnings": list(plan.warnings)}
    desired: dict[str, int] = {}
    for symbol, weight in targets.items():
        price = open_prices.get(symbol)
        if price and price > 0:
            desired[symbol] = floor(nav * weight / price / BUY_LOT) * BUY_LOT
        else:
            plan.warnings.append(f"missing_open_for_target:{symbol}")
    fills: list[Fill] = []
    for symbol, current in sorted(book.holdings.items()):
        target = desired.get(symbol, 0)
        if current > target:
            fill = _sell_fifo(book, plan.plan_id, symbol, current - target, open_prices[symbol], trade_date)
            if fill:
                fills.append(fill)
    for symbol, target in sorted(desired.items()):
        current = book.shares(symbol)
        if target > current:
            fill = _buy(book, plan.plan_id, symbol, target - current, open_prices[symbol], trade_date)
            if fill:
                fills.append(fill)
    for symbol, amount in sorted(plan.cash_buys.items()):
        price = open_prices.get(symbol)
        if price and price > 0 and amount > 0:
            fill = _buy(book, plan.plan_id, symbol, floor(amount / price), price, trade_date)
            if fill:
                fills.append(fill)
        else:
            plan.warnings.append(f"cash_buy_unfilled:{symbol}")
    plan.status = "FILLED" if not plan.warnings else "PARTIAL"
    result = {"status": plan.status, "fills": [fill.__dict__ for fill in fills], "warnings": list(plan.warnings)}
    book.pending_plan = None
    return result


def _normalize_action_dates(actions: pd.DataFrame) -> pd.DataFrame:
    result = actions.copy()
    for column in ("record_date", "pay_date", "ex_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column].astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    return result


def process_dividends(book: Book, trade_date: str, actions: pd.DataFrame) -> tuple[dict[str, float], list[str]]:
    if actions.empty:
        return {}, []
    actions = _normalize_action_dates(actions)
    warnings: list[str] = []
    existing = {ent.entitlement_id for ent in book.entitlements}
    records = actions[actions["record_date"].eq(trade_date)] if "record_date" in actions else pd.DataFrame()
    for row in records.to_dict("records"):
        symbol = str(row.get("ts_code", ""))
        cash_div = float(row.get("cash_div") or 0.0)
        pay_date = row.get("pay_date")
        shares = book.shares(symbol)
        entitlement_id = f"{symbol}:{trade_date}:{pay_date}:{cash_div}"
        if shares <= 0 or cash_div <= 0 or not pay_date or entitlement_id in existing:
            continue
        book.entitlements.append(DividendEntitlement(entitlement_id, symbol, trade_date, pay_date, shares, cash_div))
        existing.add(entitlement_id)
        for lot in book.lots.get(symbol, []):
            lot.taxable_dividend_per_share += cash_div
    reinvest: dict[str, float] = {}
    for ent in book.entitlements:
        if ent.credited or ent.pay_date != trade_date:
            continue
        gross = ent.shares * ent.cash_div_per_share
        book.cash += gross
        ent.credited = True
        reinvest[ent.symbol] = reinvest.get(ent.symbol, 0.0) + gross
        book.cash_events.append(CashEvent(uuid4().hex, trade_date, ent.symbol, "DIVIDEND_CREDIT", gross, 0.0, gross))
    pays = actions[actions["pay_date"].eq(trade_date)] if "pay_date" in actions else pd.DataFrame()
    for row in pays.to_dict("records"):
        symbol = str(row.get("ts_code", ""))
        if book.shares(symbol) > 0 and not any(ent.symbol == symbol and ent.pay_date == trade_date for ent in book.entitlements):
            warnings.append(f"missing_record_date_entitlement:{symbol}")
    return reinvest, warnings


def _record_nav(book: Book, trade_date: str, close_prices: dict[str, float]) -> tuple[float, list[str]]:
    for symbol, price in close_prices.items():
        if price > 0:
            book.last_prices[symbol] = price
    nav, warnings = book_nav(book, close_prices)
    prev = float(book.nav_history[-1]["nav"]) if book.nav_history else nav
    ret = nav / prev - 1.0 if prev else 0.0
    book.nav_history.append({"date": trade_date, "nav": round(nav, 2), "ret": round(ret, 8)})
    return nav, warnings


def _voltrend_position(book: Book, current_nav: float) -> float:
    returns = [float(row["ret"]) for row in book.nav_history]
    vol = float(np.std(returns[-VOL_WINDOW:], ddof=0) * np.sqrt(252)) if len(returns) >= 10 else 0.0
    vol_position = min(1.0, TARGET_VOL / vol) if vol > 0 else 1.0
    navs = [float(row["nav"]) for row in book.nav_history]
    moving_average = float(np.mean(navs[-MA_N:])) if len(navs) >= MA_N else current_nav
    return round(vol_position * (1.0 if current_nav >= moving_average else 0.0), 4)


def _queue_plan(book: Book, signal_date: str, execute_date: str | None, target_weights: dict[str, float], reason: str, cash_buys: dict[str, float] | None = None) -> list[str]:
    if execute_date is None:
        return ["next_trading_day_unavailable"]
    if book.pending_plan and book.pending_plan.status == "PENDING":
        return [f"pending_plan_not_replaced:{book.pending_plan.plan_id}"]
    book.pending_plan = PendingPlan(uuid4().hex, book.name, signal_date, execute_date, target_weights, cash_buys or {}, reason)
    return []


def _composite_drawdown(state: PaperState) -> float:
    div = state.dividend_book.nav_history
    vol = state.voltrend_book.nav_history
    if not div or not vol:
        return 0.0
    navs = [float(a["nav"]) + float(b["nav"]) for a, b in zip(div, vol)]
    return navs[-1] / max(navs) - 1.0 if max(navs) else 0.0


def run_day(state: PaperState, store: DataStore, trade_date: str) -> dict:
    if state.legacy_import:
        return {"date": trade_date, "status": "BLOCKED", "errors": ["legacy_state_requires_reset_or_verified_import"]}
    trade_date = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    if any(row.get("date") == trade_date and row.get("status") == "COMPLETE" for row in state.run_history):
        return {"date": trade_date, "already_executed": True}
    open_prices = store.prices(trade_date, "open")
    close_prices = store.prices(trade_date, "close")
    if not open_prices or not close_prices:
        return {"date": trade_date, "status": "BLOCKED", "errors": ["missing_open_or_close_prices"]}
    div_exec = execute_pending_plan(state.dividend_book, trade_date, open_prices)
    vol_exec = execute_pending_plan(state.voltrend_book, trade_date, open_prices)
    actions = store.corporate_actions()
    div_reinvest, div_warnings = process_dividends(state.dividend_book, trade_date, actions)
    _, vol_div_warnings = process_dividends(state.voltrend_book, trade_date, actions)
    div_nav, div_mark_warnings = _record_nav(state.dividend_book, trade_date, close_prices)
    vol_nav, vol_mark_warnings = _record_nav(state.voltrend_book, trade_date, close_prices)
    if not state.start_date:
        state.start_date = trade_date
    warnings = div_warnings + vol_div_warnings + div_mark_warnings + vol_mark_warnings
    next_day = store.next_trading_day(trade_date)
    month_end = store.is_last_trading_day_of_month(trade_date)
    first_div_signal = not state.dividend_book.model_weights
    if first_div_signal or month_end:
        weights = dividend_weights(store, trade_date)
        if weights:
            state.dividend_book.model_weights = weights
            warnings += _queue_plan(state.dividend_book, trade_date, next_day, weights, "MONTHLY_DIVIDEND")
        else:
            warnings.append("empty_dividend_universe")
    elif div_reinvest:
        warnings += _queue_plan(state.dividend_book, trade_date, next_day, {}, "DIVIDEND_REINVEST_SAME_STOCK", div_reinvest)
    first_vol_signal = not state.voltrend_book.model_weights
    if first_vol_signal or month_end:
        weights = balanced_weights(store, trade_date)
        if weights:
            state.voltrend_book.model_weights = weights
        else:
            warnings.append("empty_voltrend_universe")
    position = _voltrend_position(state.voltrend_book, vol_nav)
    drawdown = _composite_drawdown(state)
    risk_status = "NORMAL"
    if drawdown <= RISK_HARD_DRAWDOWN and RISK_HARD_ACTION == "VOL_TO_CASH":
        position = 0.0
        risk_status = "HARD_VOL_TO_CASH"
    elif drawdown <= RISK_ALERT_DRAWDOWN:
        risk_status = "ALERT"
    if state.voltrend_book.model_weights and (first_vol_signal or month_end or abs(position - state.voltrend_book.risk_position) >= 0.01):
        state.voltrend_book.risk_position = position
        targets = {symbol: weight * position for symbol, weight in state.voltrend_book.model_weights.items()}
        warnings += _queue_plan(state.voltrend_book, trade_date, next_day, targets, "VOL_TARGET_TREND")
    result = {
        "date": trade_date,
        "status": "COMPLETE",
        "month_end": month_end,
        "next_execution_date": next_day,
        "dividend_nav": round(div_nav, 2),
        "voltrend_nav": round(vol_nav, 2),
        "total_nav": round(div_nav + vol_nav, 2),
        "drawdown": round(drawdown, 6),
        "risk_status": risk_status,
        "dividend_execution": div_exec,
        "voltrend_execution": vol_exec,
        "warnings": sorted(set(warnings)),
    }
    state.run_history.append(result)
    return result

