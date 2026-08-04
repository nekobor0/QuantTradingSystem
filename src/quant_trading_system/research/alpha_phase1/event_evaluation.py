"""Event identification and matched-CAR summaries for the V3 event channel."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .classified_evaluation import newey_west_summary


def identify_first_sealed_limit_up(frame: pd.DataFrame) -> pd.Series:
    ordered = frame.sort_values("signal_date")
    sealed = ordered["close"].sub(ordered["up_limit"]).abs().le(0.001) & ordered["volume"].gt(0)
    first = sealed & ~sealed.shift(1, fill_value=False)
    return first.reindex(frame.index, fill_value=False)


def map_to_effective_trading_date(
    announcement_dates: pd.Series, trading_dates: pd.DatetimeIndex
) -> pd.Series:
    """Map an announcement to the first trading date on or after publication."""
    calendar = pd.DatetimeIndex(trading_dates).sort_values().unique()
    values = pd.to_datetime(announcement_dates, errors="coerce")
    positions = calendar.searchsorted(values, side="left")
    mapped = pd.Series(pd.NaT, index=announcement_dates.index, dtype="datetime64[ns]")
    valid = values.notna() & (positions < len(calendar))
    mapped.loc[valid] = calendar.take(positions[valid])
    return mapped


def keep_events_after_cooldown(frame: pd.DataFrame, days: int) -> pd.Series:
    """Keep the first event and later events outside a same-stock calendar-day cooldown."""
    ordered = frame.sort_values(["ts_code", "signal_date"])
    previous = ordered.groupby("ts_code")["signal_date"].shift()
    keep = previous.isna() | ordered["signal_date"].sub(previous).dt.days.ge(days)
    return keep.reindex(frame.index, fill_value=False)


def summarize_matched_events(events: pd.DataFrame, horizon: int) -> dict[str, Any]:
    matched_column = f"matched_car_{horizon}"
    market_column = f"market_car_{horizon}"
    valid = events.dropna(subset=[matched_column, market_column]).copy()
    daily_matched = valid.groupby("signal_date")[matched_column].mean()
    daily_market = valid.groupby("signal_date")[market_column].mean()
    matched = newey_west_summary(daily_matched, max(horizon - 1, 0))
    market = newey_west_summary(daily_market, max(horizon - 1, 0))
    total_market_alpha = float(daily_market.mean()) if len(daily_market) else None
    event_alpha = float(daily_matched.mean()) if len(daily_matched) else None
    event_share = event_alpha / total_market_alpha if total_market_alpha and total_market_alpha > 0 else None
    return {
        "events": int(len(valid)),
        "event_days": int(valid["signal_date"].nunique()),
        "matched_car": matched,
        "market_car": market,
        "event_specific_share": event_share,
        "style_share": 1.0 - event_share if event_share is not None else None,
    }
