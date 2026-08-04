"""Preregistered Lane F industry-relative momentum signal."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_industry_momentum_scores(
    industry_returns: pd.DataFrame,
    *,
    history_months: int = 11,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"signal_date", "exit_date", "l1_code", "industry_return"}
    missing = required.difference(industry_returns.columns)
    if missing:
        raise ValueError(f"missing industry momentum columns: {sorted(missing)}")
    if history_months <= 0:
        raise ValueError("history_months must be positive")
    source = industry_returns.copy()
    source["signal_date"] = pd.to_datetime(source["signal_date"])
    source["exit_date"] = pd.to_datetime(source["exit_date"])
    rows: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    for signal_date in sorted(source["signal_date"].unique()):
        available = source[source["exit_date"].le(signal_date)]
        momentum: dict[str, float] = {}
        latest_exit: dict[str, pd.Timestamp] = {}
        for industry, history in available.groupby("l1_code"):
            trailing = history.sort_values("exit_date").tail(history_months)
            if len(trailing) < history_months:
                continue
            momentum[str(industry)] = float((1.0 + trailing["industry_return"]).prod() - 1.0)
            latest_exit[str(industry)] = pd.Timestamp(trailing["exit_date"].max())
        cross_mean = float(np.mean(list(momentum.values()))) if momentum else np.nan
        for industry, value in momentum.items():
            rows.append(
                {
                    "signal_date": signal_date,
                    "l1_code": industry,
                    "industry_momentum": value,
                    "relative_momentum": value - cross_mean,
                }
            )
            audits.append(
                {
                    "signal_date": signal_date,
                    "l1_code": industry,
                    "history_months": history_months,
                    "latest_used_exit_date": latest_exit[industry],
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(audits)
