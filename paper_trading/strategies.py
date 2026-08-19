"""Read-only strategy preview helpers kept separate from execution."""

from __future__ import annotations

from .market import DataStore, balanced_weights, dividend_weights
from .models import PaperState


def scan(state: PaperState, store: DataStore, trade_date: str) -> dict:
    dividend = dividend_weights(store, trade_date)
    voltrend = balanced_weights(store, trade_date)
    return {
        "date": trade_date,
        "is_month_end": store.is_last_trading_day_of_month(trade_date),
        "next_execution_date": store.next_trading_day(trade_date),
        "dividend_target_count": len(dividend),
        "voltrend_target_count": len(voltrend),
        "dividend_target": list(dividend)[:20],
        "voltrend_target": list(voltrend)[:20],
        "current_dividend_holdings": len(state.dividend_book.holdings),
        "current_voltrend_holdings": len(state.voltrend_book.holdings),
        "dividend_pending_plan": (
            state.dividend_book.pending_plan.__dict__ if state.dividend_book.pending_plan else None
        ),
        "voltrend_pending_plan": (
            state.voltrend_book.pending_plan.__dict__ if state.voltrend_book.pending_plan else None
        ),
    }
