"""Frozen overlapping three-month tail evaluator for quarterly V4 factors."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.classified_evaluation import newey_west_summary
from quant_trading_system.research.alpha_phase1.long_only_evaluation import (
    quality_summary,
    turnover_summary,
)


def slow_tail_series(
    frame: pd.DataFrame,
    factor: str,
    *,
    mask: pd.Series | None = None,
    fraction: float = 0.05,
    fixed_two_way_cost: float = 0.0005,
) -> tuple[pd.Series, dict[pd.Timestamp, dict[str, float]], dict[str, float | None]]:
    selected = frame["eligible_evaluation"] if mask is None else frame["eligible_evaluation"] & mask
    values: dict[pd.Timestamp, float] = {}
    holdings: dict[pd.Timestamp, dict[str, float]] = {}
    industry_weights = []
    contributions: dict[str, float] = {}
    for date, group in frame.loc[selected].groupby("signal_date", sort=True):
        candidates = group.dropna(subset=[factor, "forward_return", "l1_code"]).sort_values(
            [factor, "ts_code"], kind="stable"
        )
        if len(candidates) < 100:
            continue
        count = max(20, int(np.ceil(len(candidates) * fraction)))
        top = candidates.tail(count)
        benchmark = float(candidates["forward_return"].mean())
        excess = top["forward_return"] - benchmark
        values[pd.Timestamp(date)] = float(excess.mean() - fixed_two_way_cost)
        weight = 1.0 / count
        holdings[pd.Timestamp(date)] = {str(symbol): weight for symbol in top["ts_code"]}
        industry_weights.append(float(top["l1_code"].value_counts(normalize=True).max()))
        for symbol, value in zip(top["ts_code"].astype(str), excess, strict=True):
            contributions[symbol] = contributions.get(symbol, 0.0) + float(value) * weight
    total = sum(contributions.values())
    concentration = (
        max((value for value in contributions.values() if value > 0), default=0.0) / total
        if total > 0
        else None
    )
    diagnostics = {
        "average_max_industry_weight": float(np.mean(industry_weights)) if industry_weights else None,
        "max_stock_cumulative_profit_share": concentration,
    }
    return pd.Series(values, dtype=float), holdings, diagnostics


def evaluate_slow_tail_factor(
    frame: pd.DataFrame, factor: str, pure_factor: str, hypothesis: str
) -> dict[str, Any]:
    raw_values, _, _ = slow_tail_series(frame, factor)
    pure_values, holdings, diagnostics = slow_tail_series(frame, pure_factor)
    raw = newey_west_summary(raw_values, 2)
    pure = newey_west_summary(pure_values, 2)
    oos_mask = frame["signal_date"] >= pd.Timestamp("2023-07-01")
    domains = {
        "oos_fixed": oos_mask,
        "hs300": frame["in_hs300"],
        "csi500_csi1000": frame["in_mid_small"],
        "main_board": frame["is_main_board"],
    }
    domain_results = {}
    for name, mask in domains.items():
        values, _, _ = slow_tail_series(frame, pure_factor, mask=mask)
        domain_results[name] = newey_west_summary(values, 2)
    raw_mean, pure_mean = raw["mean"], pure["mean"]
    same_direction = bool(raw_mean is not None and raw_mean > 0 and pure_mean is not None and pure_mean > 0)
    suppression_release = bool(raw_mean is not None and raw_mean <= 0 and pure_mean is not None and pure_mean > 0)
    retention = pure_mean / raw_mean if same_direction and raw_mean else None
    quality = quality_summary(frame, factor)
    turnover = turnover_summary(holdings)
    checks = {
        "missing_rate_lt_5pct": quality["missing_rate"] is not None and quality["missing_rate"] < 0.05,
        "float_mv_coverage_ge_80pct": quality["float_mv_coverage"] is not None and quality["float_mv_coverage"] >= 0.80,
        "pure_3m_net_excess_gt_3pct": pure_mean is not None and pure_mean > 0.03,
        "pure_3m_hac_t_gt_2_5": pure["t_stat_hac"] is not None and pure["t_stat_hac"] > 2.5,
        "pure_3m_win_rate_gt_65pct": pure["positive_ratio"] is not None and pure["positive_ratio"] > 0.65,
        "monthly_one_way_turnover_lt_100pct": turnover["monthly_one_way_mean"] is not None and turnover["monthly_one_way_mean"] < 1.0,
        "average_max_industry_weight_lt_30pct": diagnostics["average_max_industry_weight"] is not None and diagnostics["average_max_industry_weight"] < 0.30,
        "max_stock_profit_share_lt_20pct": diagnostics["max_stock_cumulative_profit_share"] is not None and diagnostics["max_stock_cumulative_profit_share"] < 0.20,
        "purity_same_direction_or_suppression_release": same_direction or suppression_release,
        "same_direction_retention_ge_50pct": suppression_release or (retention is not None and retention >= 0.50),
        **{
            f"{name}_pure_positive": result["mean"] is not None and result["mean"] > 0
            for name, result in domain_results.items()
        },
    }
    return {
        "channel": "slow_tail_3m",
        "hypothesis": hypothesis,
        "quality": quality,
        "raw_3m": raw,
        "pure_3m": pure,
        "fixed_two_way_cost": 0.0005,
        "turnover": turnover,
        "diagnostics": diagnostics,
        "domains": domain_results,
        "suppression_release": suppression_release,
        "same_direction_retention": retention,
        "gate_checks": {name: bool(value) for name, value in checks.items()},
        "passes_all_gates": bool(all(checks.values())),
    }
