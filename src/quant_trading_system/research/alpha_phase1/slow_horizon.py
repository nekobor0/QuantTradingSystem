"""Frozen T+1-open labels for slow quarterly style and fundamental signals."""

from __future__ import annotations

import numpy as np
import pandas as pd


def horizon_dates(
    open_dates: list[pd.Timestamp],
    signal_dates: list[pd.Timestamp],
    horizons: tuple[int, ...] = (1, 3, 6, 12),
) -> tuple[dict[pd.Timestamp, pd.Timestamp], dict[int, dict[pd.Timestamp, pd.Timestamp]]]:
    positions = {date: number for number, date in enumerate(open_dates)}
    entry = {
        date: open_dates[positions[date] + 1]
        for date in signal_dates
        if date in positions and positions[date] + 1 < len(open_dates)
    }
    exits: dict[int, dict[pd.Timestamp, pd.Timestamp]] = {}
    for horizon in horizons:
        mapping = {}
        for number, date in enumerate(signal_dates):
            if number + horizon >= len(signal_dates):
                continue
            future_signal = signal_dates[number + horizon]
            if future_signal in positions and positions[future_signal] + 1 < len(open_dates):
                mapping[date] = open_dates[positions[future_signal] + 1]
        exits[horizon] = mapping
    return entry, exits


def sample_slow_labels(
    daily: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    entry_dates: dict[pd.Timestamp, pd.Timestamp],
    exit_dates: dict[int, dict[pd.Timestamp, pd.Timestamp]],
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
    output = pd.DataFrame({"signal_date": signal_dates})
    output["entry_tradable"] = [
        bool(tradable.get(entry_dates.get(date), False)) for date in signal_dates
    ]
    for horizon, mapping in exit_dates.items():
        returns = []
        exits = []
        for date in signal_dates:
            entry = entry_dates.get(date)
            exit_ = mapping.get(date)
            can_exit = bool(tradable.get(exit_, False))
            exits.append(can_exit)
            if bool(tradable.get(entry, False)) and can_exit:
                returns.append(adjusted_close.get(exit_, np.nan) / adjusted_open.get(entry, np.nan) - 1)
            else:
                returns.append(np.nan)
        output[f"forward_return_{horizon}m"] = returns
        output[f"exit_{horizon}m_tradable"] = exits
    return output
