"""Execution labels for monthly T+1-open portfolio rebalancing."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sample_monthly_execution(
    daily: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    entry_dates: dict[pd.Timestamp, pd.Timestamp],
    exit_dates: dict[pd.Timestamp, pd.Timestamp],
) -> pd.DataFrame:
    ordered = daily.sort_values("date").set_index("date")
    adjusted_open = ordered["open"] * ordered["factor"]
    adjusted_close = ordered["close"] * ordered["factor"]
    previous_close = ordered["close"].shift(1)
    absolute_return = (ordered["close"] / previous_close - 1).abs()
    one_price = ordered[["open", "high", "low", "close"]].max(axis=1).eq(
        ordered[["open", "high", "low", "close"]].min(axis=1)
    )
    tradable = ordered["volume"].gt(0) & ~(one_price & absolute_return.ge(0.045))

    valuation_dates = sorted(
        {
            value
            for value in [*entry_dates.values(), *exit_dates.values()]
            if value is not None
        }
    )
    mark_index = adjusted_close.index.union(pd.DatetimeIndex(valuation_dates)).sort_values()
    last_close_marks = adjusted_close.reindex(mark_index).ffill()

    rows = []
    for signal_date in signal_dates:
        entry = entry_dates.get(signal_date)
        exit_ = exit_dates.get(signal_date)
        entry_price = adjusted_open.get(entry, np.nan)
        exit_price = adjusted_open.get(exit_, np.nan)
        if entry is not None and not np.isfinite(entry_price):
            entry_price = last_close_marks.get(entry, np.nan)
        if exit_ is not None and not np.isfinite(exit_price):
            exit_price = last_close_marks.get(exit_, np.nan)
        rows.append(
            {
                "signal_date": signal_date,
                "entry_date": entry,
                "exit_date": exit_,
                "entry_tradable": bool(tradable.get(entry, False)),
                "exit_tradable": bool(tradable.get(exit_, False)),
                "mark_return_1m": (
                    float(exit_price / entry_price - 1)
                    if np.isfinite(entry_price) and np.isfinite(exit_price) and entry_price > 0
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)
