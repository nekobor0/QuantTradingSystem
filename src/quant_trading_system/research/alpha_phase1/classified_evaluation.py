"""Frozen V3 classified evaluators for monthly dense and tail factors."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .long_only_evaluation import monthly_ic, quality_summary, series_summary, turnover_summary


def tail_analysis(
    frame: pd.DataFrame,
    factor: str,
    *,
    fraction: float = 0.05,
    mask: pd.Series | None = None,
    minimum_names: int = 20,
) -> tuple[dict[str, Any], dict[pd.Timestamp, dict[str, float]]]:
    selected = frame["eligible_evaluation"] if mask is None else frame["eligible_evaluation"] & mask
    monthly: dict[pd.Timestamp, float] = {}
    holdings: dict[pd.Timestamp, dict[str, float]] = {}
    industry_weights: list[float] = []
    contributions: dict[str, float] = {}
    for date, group in frame.loc[selected].groupby("signal_date", sort=True):
        candidates = group.dropna(subset=[factor, "forward_return", "l1_code"]).sort_values(
            [factor, "ts_code"], kind="stable"
        )
        if len(candidates) < minimum_names:
            continue
        count = max(minimum_names, int(np.ceil(len(candidates) * fraction)))
        if count > len(candidates):
            continue
        top = candidates.tail(count).copy()
        benchmark = float(candidates["forward_return"].mean())
        excess = top["forward_return"] - benchmark
        monthly[pd.Timestamp(date)] = float(excess.mean())
        weight = 1.0 / len(top)
        holdings[pd.Timestamp(date)] = {str(symbol): weight for symbol in top["ts_code"]}
        industry_weights.append(float(top["l1_code"].value_counts(normalize=True).max()))
        for symbol, value in zip(top["ts_code"].astype(str), excess, strict=True):
            contributions[symbol] = contributions.get(symbol, 0.0) + float(value) * weight

    summary = series_summary(pd.Series(monthly, dtype=float))
    total = sum(contributions.values())
    max_stock_share = (
        max((value for value in contributions.values() if value > 0), default=0.0) / total
        if total > 0
        else None
    )
    return {
        "fraction": fraction,
        "minimum_names": minimum_names,
        "excess": summary,
        "worst_month": min(monthly.values()) if monthly else None,
        "average_max_industry_weight": float(np.mean(industry_weights)) if industry_weights else None,
        "max_stock_cumulative_profit_share": max_stock_share,
        "turnover": turnover_summary(holdings),
    }, holdings


def evaluate_tail_factor(
    frame: pd.DataFrame,
    factor: str,
    pure_factor: str,
    hypothesis: str,
) -> dict[str, Any]:
    raw, _ = tail_analysis(frame, factor)
    pure, _ = tail_analysis(frame, pure_factor)
    last_period = frame["signal_date"].max().to_period("M")
    cutoff = (last_period - 35).to_timestamp()
    domains = {
        "oos_3y": frame["signal_date"] >= cutoff,
        "hs300": frame["in_hs300"],
        "csi500_csi1000": frame["in_mid_small"],
        "main_board": frame["is_main_board"],
    }
    domain_results = {
        name: tail_analysis(frame, pure_factor, mask=mask)[0]["excess"] for name, mask in domains.items()
    }
    raw_mean = raw["excess"]["mean"]
    pure_mean = pure["excess"]["mean"]
    same_direction = bool(raw_mean is not None and raw_mean > 0 and pure_mean is not None and pure_mean > 0)
    suppression_release = bool(raw_mean is not None and raw_mean <= 0 and pure_mean is not None and pure_mean > 0)
    retention = pure_mean / raw_mean if same_direction and raw_mean else None
    quality = quality_summary(frame, factor)
    checks = {
        "missing_rate_lt_5pct": quality["missing_rate"] is not None and quality["missing_rate"] < 0.05,
        "float_mv_coverage_ge_80pct": quality["float_mv_coverage"] is not None and quality["float_mv_coverage"] >= 0.80,
        "pure_tail_mean_gt_1pct": pure_mean is not None and pure_mean > 0.01,
        "pure_tail_t_gt_2_5": pure["excess"]["t_stat"] is not None and pure["excess"]["t_stat"] > 2.5,
        "pure_tail_win_rate_gt_65pct": pure["excess"]["positive_ratio"] is not None and pure["excess"]["positive_ratio"] > 0.65,
        "worst_month_gt_minus_15pct": pure["worst_month"] is not None and pure["worst_month"] > -0.15,
        "monthly_two_way_turnover_lt_200pct": pure["turnover"]["monthly_one_way_mean"] is not None and pure["turnover"]["monthly_one_way_mean"] < 1.0,
        "average_max_industry_weight_lt_30pct": pure["average_max_industry_weight"] is not None and pure["average_max_industry_weight"] < 0.30,
        "max_stock_profit_share_lt_20pct": pure["max_stock_cumulative_profit_share"] is not None and pure["max_stock_cumulative_profit_share"] < 0.20,
        "purity_same_direction_or_suppression_release": same_direction or suppression_release,
        "same_direction_retention_ge_50pct": suppression_release or (retention is not None and retention >= 0.50),
        **{
            f"{name}_pure_tail_positive": value["mean"] is not None and value["mean"] > 0
            for name, value in domain_results.items()
        },
    }
    return {
        "channel": "tail",
        "hypothesis": hypothesis,
        "quality": quality,
        "raw_tail": raw,
        "pure_tail": pure,
        "suppression_release": suppression_release,
        "same_direction_retention": retention,
        "domains": domain_results,
        "gate_checks": {name: bool(value) for name, value in checks.items()},
        "passes_all_gates": bool(all(checks.values())),
    }


def evaluate_dense_factor_v3(
    frame: pd.DataFrame,
    factor: str,
    pure_factor: str,
    hypothesis: str,
) -> dict[str, Any]:
    from .long_only_evaluation import decile_analysis

    pure_ic = monthly_ic(frame, pure_factor)
    pure_deciles, holdings = decile_analysis(frame, pure_factor)
    last_period = frame["signal_date"].max().to_period("M")
    cutoff = (last_period - 35).to_timestamp()
    domains = {
        "oos_3y": frame["signal_date"] >= cutoff,
        "hs300": frame["in_hs300"],
        "csi500_csi1000": frame["in_mid_small"],
        "main_board": frame["is_main_board"],
    }
    domain_results = {
        name: decile_analysis(frame, pure_factor, mask)[0]["d1_excess"] for name, mask in domains.items()
    }
    quality = quality_summary(frame, factor)
    ic = series_summary(pure_ic)
    d1 = pure_deciles["d1_excess"]
    checks = {
        "missing_rate_lt_5pct": quality["missing_rate"] is not None and quality["missing_rate"] < 0.05,
        "float_mv_coverage_ge_80pct": quality["float_mv_coverage"] is not None and quality["float_mv_coverage"] >= 0.80,
        "pure_ic_gt_003": ic["mean"] is not None and ic["mean"] > 0.03,
        "pure_ic_ir_gt_05": ic["ir"] is not None and ic["ir"] > 0.5,
        "pure_ic_positive_ratio_gt_60pct": ic["positive_ratio"] is not None and ic["positive_ratio"] > 0.60,
        "pure_d1_positive": d1["mean"] is not None and d1["mean"] > 0,
        "pure_d1_t_gt_2": d1["t_stat"] is not None and d1["t_stat"] > 2.0,
        "monotonic_pairs_ge_8": pure_deciles["increasing_adjacent_pairs"] >= 8,
        "d1_gt_d10": pure_deciles["d1_minus_d10"] > 0,
        **{
            f"{name}_pure_d1_positive": value["mean"] is not None and value["mean"] > 0
            for name, value in domain_results.items()
        },
    }
    return {
        "channel": "dense",
        "hypothesis": hypothesis,
        "quality": quality,
        "pure_ic": ic,
        "pure_deciles": pure_deciles,
        "turnover": turnover_summary(holdings),
        "domains": domain_results,
        "gate_checks": {name: bool(value) for name, value in checks.items()},
        "passes_all_gates": bool(all(checks.values())),
    }


def newey_west_summary(values: pd.Series, lags: int) -> dict[str, float | int | None]:
    clean = values.dropna().astype(float).to_numpy()
    count = len(clean)
    if count < 2:
        return {"observations": count, "mean": None, "t_stat_hac": None, "positive_ratio": None}
    mean = float(clean.mean())
    demeaned = clean - mean
    long_run = float(demeaned @ demeaned / count)
    for lag in range(1, min(lags, count - 1) + 1):
        covariance = float(demeaned[lag:] @ demeaned[:-lag] / count)
        long_run += 2.0 * (1.0 - lag / (lags + 1.0)) * covariance
    standard_error = np.sqrt(max(long_run, 0.0) / count)
    return {
        "observations": count,
        "mean": mean,
        "t_stat_hac": mean / standard_error if standard_error > 0 else None,
        "positive_ratio": float((clean > 0).mean()),
    }


def short_top_group_series(
    frame: pd.DataFrame,
    factor: str,
    horizon: int,
    *,
    fraction: float = 0.10,
    fixed_two_way_cost: float = 0.0005,
) -> tuple[pd.Series, dict[pd.Timestamp, dict[str, float]]]:
    returns: dict[pd.Timestamp, float] = {}
    holdings: dict[pd.Timestamp, dict[str, float]] = {}
    label = f"forward_return_{horizon}"
    for date, group in frame.loc[frame["eligible_evaluation"]].groupby("signal_date", sort=True):
        candidates = group.dropna(subset=[factor, label]).sort_values([factor, "ts_code"], kind="stable")
        if len(candidates) < 100:
            continue
        count = max(20, int(np.ceil(len(candidates) * fraction)))
        top = candidates.tail(count)
        benchmark = float(candidates[label].mean())
        returns[pd.Timestamp(date)] = float(top[label].mean() - benchmark - fixed_two_way_cost)
        weight = 1.0 / len(top)
        holdings[pd.Timestamp(date)] = {str(symbol): weight for symbol in top["ts_code"]}
    return pd.Series(returns, dtype=float), holdings


def evaluate_short_factor(
    frame: pd.DataFrame,
    factor: str,
    pure_factor: str,
    hypothesis: str,
) -> dict[str, Any]:
    horizon_results: dict[str, Any] = {}
    primary_holdings: dict[pd.Timestamp, dict[str, float]] = {}
    for horizon in (1, 5, 10, 20):
        values, holdings = short_top_group_series(frame, pure_factor, horizon)
        horizon_results[str(horizon)] = newey_west_summary(values, max(horizon - 1, 0))
        if horizon == 5:
            primary_holdings = holdings
    primary = horizon_results["5"]
    raw_values, _ = short_top_group_series(frame, factor, 5)
    raw_primary = newey_west_summary(raw_values, 4)
    raw_mean = raw_primary["mean"]
    pure_mean = primary["mean"]
    same_direction = bool(raw_mean is not None and raw_mean > 0 and pure_mean is not None and pure_mean > 0)
    suppression_release = bool(raw_mean is not None and raw_mean <= 0 and pure_mean is not None and pure_mean > 0)
    retention = pure_mean / raw_mean if same_direction and raw_mean else None
    cutoff = frame["signal_date"].max() - pd.DateOffset(years=3)
    oos_values, _ = short_top_group_series(frame.loc[frame["signal_date"] >= cutoff], pure_factor, 5)
    oos = newey_west_summary(oos_values, 4)
    common_turnover = turnover_summary(primary_holdings)
    turnover = {
        "transitions": common_turnover["transitions"],
        "daily_one_way_mean": common_turnover["monthly_one_way_mean"],
        "daily_one_way_max": common_turnover["monthly_one_way_max"],
    }
    quality = quality_summary(frame, factor)
    checks = {
        "missing_rate_lt_5pct": quality["missing_rate"] is not None and quality["missing_rate"] < 0.05,
        "float_mv_coverage_ge_80pct": quality["float_mv_coverage"] is not None and quality["float_mv_coverage"] >= 0.80,
        "primary_5d_net_excess_gt_05pct": primary["mean"] is not None and primary["mean"] > 0.005,
        "primary_5d_hac_t_gt_2_5": primary["t_stat_hac"] is not None and primary["t_stat_hac"] > 2.5,
        "daily_one_way_turnover_lt_30pct": turnover["daily_one_way_mean"] is not None and turnover["daily_one_way_mean"] < 0.30,
        "oos_3y_net_excess_positive": oos["mean"] is not None and oos["mean"] > 0,
        "purity_same_direction_or_suppression_release": same_direction or suppression_release,
        "same_direction_retention_ge_50pct": suppression_release or (retention is not None and retention >= 0.50),
    }
    return {
        "channel": "short_horizon",
        "hypothesis": hypothesis,
        "quality": quality,
        "fixed_two_way_cost": 0.0005,
        "raw_primary_5d": raw_primary,
        "suppression_release": suppression_release,
        "same_direction_retention": retention,
        "horizons": horizon_results,
        "oos_3y_primary": oos,
        "turnover": turnover,
        "gate_checks": {name: bool(value) for name, value in checks.items()},
        "passes_all_gates": bool(all(checks.values())),
    }
