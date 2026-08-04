"""Frozen daily signals and T+1-open tradable labels for V4 short-horizon research."""

from __future__ import annotations

import numpy as np
import pandas as pd


HORIZONS = (1, 2, 3, 5, 10, 20)


def _rolling_zscore(values: pd.Series, window: int = 120, minimum: int = 60) -> pd.Series:
    mean = values.rolling(window, min_periods=minimum).mean()
    std = values.rolling(window, min_periods=minimum).std(ddof=0).replace(0, np.nan)
    return (values - mean) / std


def calculate_short_signals(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values("date").set_index("date")
    adjusted = ordered["close"] * ordered["factor"]
    adjusted_open = ordered["open"] * ordered["factor"]
    returns = adjusted.pct_change(fill_method=None)
    log_volume = np.log1p(ordered["volume"])
    volume_mean_5 = log_volume.rolling(5, min_periods=5).mean()
    return_5 = adjusted.pct_change(5, fill_method=None)
    volume_change_5 = volume_mean_5.diff(5)
    output = pd.DataFrame(index=ordered.index)
    output["formulaic_012_daily"] = np.sign(ordered["volume"].diff()) * -returns
    output["price_volume_divergence_5d"] = _rolling_zscore(volume_change_5) - _rolling_zscore(return_5)
    output["volatility_60"] = returns.rolling(60, min_periods=40).std()
    output["momentum_12_1"] = adjusted.shift(20) / adjusted.shift(252) - 1
    output["adjusted_close"] = adjusted
    previous_close = ordered["close"].shift(1)
    absolute_return = (ordered["close"] / previous_close - 1).abs()
    one_price = ordered[["open", "high", "low", "close"]].max(axis=1).eq(
        ordered[["open", "high", "low", "close"]].min(axis=1)
    )
    output["tradable"] = ordered["volume"].gt(0) & ~(one_price & absolute_return.ge(0.045))
    for horizon in HORIZONS:
        entry = adjusted_open.shift(-1)
        exit_ = adjusted.shift(-(horizon + 1))
        entry_tradable = output["tradable"].shift(-1, fill_value=False).astype(bool)
        exit_tradable = output["tradable"].shift(-(horizon + 1), fill_value=False).astype(bool)
        output[f"forward_return_{horizon}"] = (exit_ / entry - 1).where(entry_tradable & exit_tradable)
        output[f"entry_tradable_{horizon}"] = entry_tradable
        output[f"exit_tradable_{horizon}"] = exit_tradable
    return output
