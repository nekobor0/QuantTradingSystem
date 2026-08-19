"""Read-only daily strategy scans for both paper portfolios."""

from __future__ import annotations

import pandas as pd

from .config import (
    DIVIDEND_CONSTITUENT_FREQUENCY,
    POSITION_REBALANCE_THRESHOLD,
    VOLTREND_CONSTITUENT_FREQUENCY,
    VOLTREND_POSITION_FREQUENCY,
)
from .execution import book_nav, voltrend_target_position
from .market import DataStore, balanced_weights, dividend_weights
from .models import Book, PaperState, StrategyAccount


def _names(store: DataStore) -> dict[str, str]:
    basic = store.read("stock_basic.parquet")
    if basic.empty or not {"ts_code", "name"}.issubset(basic.columns):
        return {}
    latest = basic.sort_values("ts_code").drop_duplicates("ts_code", keep="last")
    return {str(code): str(name) for code, name in zip(latest["ts_code"], latest["name"])}


def _constituent_changes(
    book: Book,
    target_weights: dict[str, float],
    names: dict[str, str],
) -> dict[str, list[dict]]:
    current = set(book.holdings)
    target = set(target_weights)

    def row(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "current_shares": book.holdings.get(symbol, 0),
            "target_weight": round(float(target_weights.get(symbol, 0.0)), 8),
        }

    return {
        "buy": [row(symbol) for symbol in sorted(target - current)],
        "sell": [row(symbol) for symbol in sorted(current - target)],
        "keep": [row(symbol) for symbol in sorted(current & target)],
    }


def _scan_strategy(
    strategy: StrategyAccount,
    trade_date: str,
    prices: dict[str, float],
    month_end: bool,
    is_open_day: bool,
    dividend: dict[str, float],
    voltrend: dict[str, float],
    names: dict[str, str],
) -> dict:
    first_dividend_signal = not strategy.dividend_book.model_weights
    first_voltrend_signal = not strategy.voltrend_book.model_weights
    dividend_constituent_due = first_dividend_signal or month_end
    voltrend_constituent_due = first_voltrend_signal or month_end
    voltrend_nav, nav_warnings = book_nav(strategy.voltrend_book, prices)
    target_position = voltrend_target_position(
        strategy.voltrend_book, voltrend_nav, trade_date
    )
    position_delta = target_position - strategy.voltrend_book.risk_position
    position_refresh_due = (
        VOLTREND_POSITION_FREQUENCY == "daily" or month_end or first_voltrend_signal
    )
    position_rebalance_due = (
        position_refresh_due and abs(position_delta) >= POSITION_REBALANCE_THRESHOLD
    )
    rebalance_due = (
        dividend_constituent_due or voltrend_constituent_due or position_rebalance_due
    )
    has_pending_plan = bool(
        strategy.dividend_book.pending_plan or strategy.voltrend_book.pending_plan
    )
    signal_status = (
        "PLAN_PENDING"
        if has_pending_plan
        else "REBALANCE_DUE"
        if rebalance_due
        else "PREVIEW_ONLY"
    )
    if not is_open_day:
        signal_status = "PREVIEW_ONLY"
    return {
        "key": strategy.key,
        "name": strategy.name,
        "dividend_weight": strategy.dividend_weight,
        "voltrend_weight": strategy.voltrend_weight,
        "signal_status": signal_status,
        "execution_triggers": {
            "dividend_constituents": {
                "due": dividend_constituent_due,
                "reason": "first_signal" if first_dividend_signal else "month_end" if month_end else "daily_preview",
            },
            "voltrend_constituents": {
                "due": voltrend_constituent_due,
                "reason": "first_signal" if first_voltrend_signal else "month_end" if month_end else "daily_preview",
            },
            "voltrend_position": {
                "due": position_rebalance_due,
                "frequency": VOLTREND_POSITION_FREQUENCY,
                "current": strategy.voltrend_book.risk_position,
                "target": target_position,
                "delta": round(position_delta, 4),
                "threshold": POSITION_REBALANCE_THRESHOLD,
            },
        },
        "dividend_target_count": len(dividend),
        "voltrend_target_count": len(voltrend),
        "dividend_target": [
            {"symbol": symbol, "name": names.get(symbol, ""), "target_weight": round(weight, 8)}
            for symbol, weight in dividend.items()
        ],
        "voltrend_target": [
            {"symbol": symbol, "name": names.get(symbol, ""), "target_weight": round(weight, 8)}
            for symbol, weight in voltrend.items()
        ],
        "dividend_changes": _constituent_changes(strategy.dividend_book, dividend, names),
        "voltrend_changes": _constituent_changes(strategy.voltrend_book, voltrend, names),
        "current_dividend_holdings": len(strategy.dividend_book.holdings),
        "current_voltrend_holdings": len(strategy.voltrend_book.holdings),
        "dividend_pending_plan": (
            strategy.dividend_book.pending_plan.__dict__
            if strategy.dividend_book.pending_plan
            else None
        ),
        "voltrend_pending_plan": (
            strategy.voltrend_book.pending_plan.__dict__
            if strategy.voltrend_book.pending_plan
            else None
        ),
        "warnings": nav_warnings,
    }


def scan(state: PaperState, store: DataStore, trade_date: str) -> dict:
    trade_date = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    dividend = dividend_weights(store, trade_date)
    voltrend = balanced_weights(store, trade_date)
    names = _names(store)
    month_end = store.is_last_trading_day_of_month(trade_date)
    prices = store.prices(trade_date, "close") if hasattr(store, "prices") else {}
    is_open_day = True
    if hasattr(store, "calendar"):
        is_open_day = pd.Timestamp(trade_date).normalize() in store.calendar()
    strategy_scans = {
        key: _scan_strategy(
            strategy,
            trade_date,
            prices,
            month_end,
            is_open_day,
            dividend,
            voltrend,
            names,
        )
        for key, strategy in state.strategies.items()
    }
    statuses = {row["signal_status"] for row in strategy_scans.values()}
    signal_status = (
        "PLAN_PENDING"
        if "PLAN_PENDING" in statuses
        else "REBALANCE_DUE"
        if "REBALANCE_DUE" in statuses
        else "PREVIEW_ONLY"
    )
    result = {
        "date": trade_date,
        "is_open_trading_day": is_open_day,
        "is_month_end": month_end,
        "signal_status": signal_status,
        "next_execution_date": store.next_trading_day(trade_date),
        "execution_policy": {
            "scan": "daily",
            "calendar": "exchange_open_days",
            "dividend_constituents": DIVIDEND_CONSTITUENT_FREQUENCY,
            "voltrend_constituents": VOLTREND_CONSTITUENT_FREQUENCY,
            "voltrend_position": VOLTREND_POSITION_FREQUENCY,
            "position_threshold": POSITION_REBALANCE_THRESHOLD,
            "execution_price": "next_trading_day_open",
        },
        "strategies": strategy_scans,
        "note": (
            "A/B 每日同步扫描；非月末成分变化仅作观察。红利和波动组股票成分按月更新，"
            "波动组目标仓位每日复算，变化达到 1% 才在下一交易日开盘执行。"
        ),
    }
    result.update(strategy_scans["A"])
    result["strategies"] = strategy_scans
    result["signal_status"] = signal_status
    return result
