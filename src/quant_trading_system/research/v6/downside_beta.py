"""Frozen V6 downside-beta signal and defensive portfolio metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_downside_beta(
    stock_returns: pd.Series,
    market_returns: pd.Series,
    window: int = 252,
    min_observations: int = 120,
    min_down_observations: int = 30,
) -> pd.DataFrame:
    """Estimate conditional beta using only negative-market days in each window."""
    aligned = pd.concat(
        [stock_returns.rename("stock"), market_returns.rename("market")],
        axis=1,
        join="inner",
    ).sort_index()
    valid = aligned.notna().all(axis=1)
    down = valid & aligned["market"].lt(0)
    x = aligned["stock"].where(down)
    y = aligned["market"].where(down)
    count = down.astype(float).rolling(window, min_periods=1).sum()
    total = valid.astype(float).rolling(window, min_periods=1).sum()
    sum_x = x.rolling(window, min_periods=1).sum()
    sum_y = y.rolling(window, min_periods=1).sum()
    numerator = (
        (x * y).rolling(window, min_periods=1).sum() - sum_x * sum_y / count
    )
    denominator = (
        (y * y).rolling(window, min_periods=1).sum() - sum_y * sum_y / count
    )
    beta = numerator / denominator
    beta = beta.where(
        total.ge(min_observations)
        & count.ge(min_down_observations)
        & denominator.gt(0)
    )
    return pd.DataFrame(
        {
            "downside_beta": beta,
            "total_observations": total,
            "down_observations": count,
        }
    )


def cross_sectional_signal(
    frame: pd.DataFrame,
    raw: str = "downside_beta",
    eligible: str | None = None,
) -> pd.DataFrame:
    """Preserve the registered raw, winsorized, standardized defensive signals."""
    result = frame.copy()
    result["raw_signal"] = result[raw]

    def transform(values: pd.Series) -> pd.DataFrame:
        valid = values.dropna()
        winsorized = values.copy()
        if not valid.empty:
            lower, upper = valid.quantile([0.01, 0.99])
            winsorized = values.clip(lower, upper)
        standard_deviation = winsorized.std(ddof=0)
        standardized = (
            (winsorized - winsorized.mean()) / standard_deviation
            if standard_deviation and np.isfinite(standard_deviation)
            else winsorized * np.nan
        )
        return pd.DataFrame(
            {
                "winsorized_signal": winsorized,
                "standardized_signal": -standardized,
            }
        )

    transform_input = result["raw_signal"]
    if eligible is not None:
        transform_input = transform_input.where(result[eligible].fillna(False))
    transformed = (
        result.assign(_transform_input=transform_input)
        .groupby("signal_date", group_keys=False)["_transform_input"]
        .apply(transform)
    )
    result[["winsorized_signal", "standardized_signal"]] = transformed[
        ["winsorized_signal", "standardized_signal"]
    ]
    return result


def downside_metrics(monthly: pd.DataFrame) -> dict[str, float | int]:
    """Compute the registered monthly defensive metrics for one portfolio."""
    ordered = monthly.sort_values("signal_date")
    portfolio = ordered["portfolio_net_return"].astype(float)
    benchmark = ordered["benchmark_return"].astype(float)
    active = portfolio - benchmark
    down = benchmark.lt(0)
    down_portfolio = portfolio[down]
    down_benchmark = benchmark[down]
    denominator = float((down_benchmark - down_benchmark.mean()).pow(2).sum())
    beta = (
        float(
            (
                (down_portfolio - down_portfolio.mean())
                * (down_benchmark - down_benchmark.mean())
            ).sum()
            / denominator
        )
        if len(down_portfolio) >= 2 and denominator > 0
        else np.nan
    )
    cumulative_portfolio = (1.0 + portfolio).cumprod()
    cumulative_benchmark = (1.0 + benchmark).cumprod()
    portfolio_drawdown = cumulative_portfolio / cumulative_portfolio.cummax() - 1.0
    benchmark_drawdown = cumulative_benchmark / cumulative_benchmark.cummax() - 1.0
    worst = active.nsmallest(min(10, len(active)))
    return {
        "months": int(len(ordered)),
        "down_months": int(down.sum()),
        "down_month_mean_active_return": float(active[down].mean()) if down.any() else np.nan,
        "downside_beta": beta,
        "down_capture_ratio": (
            float(down_portfolio.sum() / down_benchmark.sum())
            if down.any() and down_benchmark.sum() != 0
            else np.nan
        ),
        "worst_5_month_mean_active_return": float(worst.iloc[:5].mean()),
        "worst_10_month_mean_active_return": float(worst.mean()),
        "maximum_drawdown": float(portfolio_drawdown.min()),
        "benchmark_maximum_drawdown": float(benchmark_drawdown.min()),
        "tracking_error": float(active.std(ddof=1) * np.sqrt(12)) if len(active) > 1 else np.nan,
        "annualized_net_excess": float(active.mean() * 12),
    }
