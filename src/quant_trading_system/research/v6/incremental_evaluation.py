"""Unified marginal portfolio evaluation for V6 research engines."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    performance_metrics,
)


def downside_beta(portfolio_return: pd.Series, benchmark_return: pd.Series) -> float:
    frame = pd.concat(
        [
            portfolio_return.rename("portfolio"),
            benchmark_return.rename("benchmark"),
        ],
        axis=1,
    ).dropna()
    downside = frame[frame["benchmark"].lt(0)]
    if len(downside) < 2:
        return np.nan
    variance = float(downside["benchmark"].var(ddof=1))
    if variance <= 0:
        return np.nan
    return float(downside["portfolio"].cov(downside["benchmark"]) / variance)


def weighted_holding_overlap(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
) -> float:
    keys = ["index_code", "signal_date", "ts_code"]
    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        if set(keys + ["weight"]).difference(frame.columns):
            raise ValueError(f"{name} holdings missing required columns")
        if frame.duplicated(keys).any():
            raise ValueError(f"{name} holdings contain duplicate keys")
    merged = baseline[keys + ["weight"]].merge(
        candidate[keys + ["weight"]],
        on=keys,
        how="outer",
        suffixes=("_baseline", "_candidate"),
    ).fillna({"weight_baseline": 0.0, "weight_candidate": 0.0})
    monthly = merged.assign(
        overlap=merged[["weight_baseline", "weight_candidate"]].min(axis=1)
    ).groupby(["index_code", "signal_date"])["overlap"].sum()
    return float(monthly.mean())


def _metric_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    keys = (
        "annual_excess_return_difference",
        "tracking_error",
        "information_ratio",
        "absolute_max_drawdown",
        "excess_max_drawdown",
        "average_monthly_one_way_turnover",
    )
    return {key: float(candidate[key] - baseline[key]) for key in keys}


def _safe_correlation(left: np.ndarray, right: np.ndarray) -> float:
    if np.std(left) <= 0 or np.std(right) <= 0:
        return np.nan
    return float(np.corrcoef(left, right)[0, 1])


def compare_portfolios(
    baseline_monthly: pd.DataFrame,
    candidate_monthly: pd.DataFrame,
    *,
    baseline_holdings: pd.DataFrame | None = None,
    candidate_holdings: pd.DataFrame | None = None,
    partial_ic: float | None = None,
    exposure_correlation: float | None = None,
) -> dict[str, Any]:
    """Compare candidate and baseline over the exact same benchmark months."""
    keys = ["index_code", "signal_date"]
    required = {
        *keys,
        "portfolio_net_return",
        "benchmark_return",
        "turnover",
    }
    for name, frame in (
        ("baseline", baseline_monthly),
        ("candidate", candidate_monthly),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name} monthly missing columns: {sorted(missing)}")
        if frame.duplicated(keys).any():
            raise ValueError(f"{name} monthly contains duplicate keys")
    common = baseline_monthly[keys].merge(candidate_monthly[keys], on=keys)
    if len(common) != len(baseline_monthly) or len(common) != len(candidate_monthly):
        raise ValueError("candidate and baseline months are not identical")

    reports: dict[str, Any] = {}
    for benchmark in sorted(baseline_monthly["index_code"].unique()):
        base = baseline_monthly[baseline_monthly["index_code"].eq(benchmark)].sort_values(
            "signal_date"
        )
        candidate = candidate_monthly[
            candidate_monthly["index_code"].eq(benchmark)
        ].sort_values("signal_date")
        base_metrics = performance_metrics(base)
        candidate_metrics = performance_metrics(candidate)
        base_active = base["portfolio_net_return"].to_numpy() - base[
            "benchmark_return"
        ].to_numpy()
        candidate_active = candidate["portfolio_net_return"].to_numpy() - candidate[
            "benchmark_return"
        ].to_numpy()
        base_downside_beta = downside_beta(
            base["portfolio_net_return"], base["benchmark_return"]
        )
        candidate_downside_beta = downside_beta(
            candidate["portfolio_net_return"], candidate["benchmark_return"]
        )
        reports[str(benchmark)] = {
            "months": int(len(base)),
            "baseline": base_metrics,
            "candidate": candidate_metrics,
            "delta": {
                **_metric_delta(candidate_metrics, base_metrics),
                "downside_beta": float(candidate_downside_beta - base_downside_beta),
            },
            "baseline_downside_beta": base_downside_beta,
            "candidate_downside_beta": candidate_downside_beta,
            "active_return_correlation": _safe_correlation(
                base_active, candidate_active
            ),
        }
    overlap = None
    if baseline_holdings is not None or candidate_holdings is not None:
        if baseline_holdings is None or candidate_holdings is None:
            raise ValueError("both holdings frames are required for overlap")
        overlap = weighted_holding_overlap(baseline_holdings, candidate_holdings)
    return {
        "benchmarks": reports,
        "weighted_holding_overlap": overlap,
        "partial_ic": partial_ic,
        "exposure_correlation": exposure_correlation,
    }
