"""Preregistered Lane D limit-down reopening event definition."""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_limit_down_reopen(
    daily: pd.DataFrame,
    *,
    price_tolerance: float = 0.001,
    close_recovery: float = 0.005,
) -> pd.Series:
    required = {"open", "high", "low", "close", "down_limit"}
    missing = required.difference(daily.columns)
    if missing:
        raise ValueError(f"missing limit-down event columns: {sorted(missing)}")
    ordered = daily.sort_index()
    down_limit = ordered["down_limit"].astype(float)
    relative_close = (ordered["close"] / down_limit - 1.0).abs()
    one_price = ordered[["open", "high", "low", "close"]].max(axis=1).sub(
        ordered[["open", "high", "low", "close"]].min(axis=1)
    ).abs().le(1e-10)
    sealed = one_price & relative_close.le(price_tolerance)
    touched = (ordered["low"] / down_limit - 1.0).abs().le(price_tolerance)
    recovered = ordered["close"].ge(down_limit * (1.0 + close_recovery))
    return (sealed.shift(1, fill_value=False) & sealed.shift(2, fill_value=False) & touched & recovered & ~sealed).reindex(daily.index)


def attach_pit_survival(events: pd.DataFrame, fundamentals: pd.DataFrame) -> pd.DataFrame:
    required_events = {"ts_code", "signal_date"}
    required_fundamentals = {
        "ts_code", "signal_date", "baseline_quality_z", "is_st", "delist_date", "l1_code"
    }
    if required_events.difference(events.columns) or required_fundamentals.difference(fundamentals.columns):
        raise ValueError("missing PIT survival columns")
    left = events.sort_values(["signal_date", "ts_code"]).copy()
    right = fundamentals.rename(columns={"signal_date": "fundamental_date"}).sort_values(
        ["fundamental_date", "ts_code"]
    )
    merged = pd.merge_asof(
        left,
        right,
        left_on="signal_date",
        right_on="fundamental_date",
        by="ts_code",
        direction="backward",
        allow_exact_matches=True,
    )
    merged["pit_survival"] = (
        merged["fundamental_date"].le(merged["signal_date"])
        & merged["baseline_quality_z"].ge(-1.0)
        & ~merged["is_st"].eq(True)
        & (merged["delist_date"].isna() | merged["delist_date"].gt(merged["signal_date"]))
    )
    return merged
