"""Capacity-aware Quality-adjusted Value primitives for C7."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from quant_trading_system.research.v6.fundamental_selection import (
    quality_adjusted_value_signal,
)


def effective_days_last_60(
    daily: pd.DataFrame,
    entries: pd.DataFrame,
) -> pd.DataFrame:
    """Count observed stock-days in the last 60 market sessions at each entry."""
    required_daily = {"ts_code", "trade_date"}
    required_entries = {"ts_code", "signal_date", "entry_date"}
    if missing := required_daily.difference(daily):
        raise ValueError(f"missing daily columns: {sorted(missing)}")
    if missing := required_entries.difference(entries):
        raise ValueError(f"missing entry columns: {sorted(missing)}")
    source = daily[list(required_daily)].copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], format="%Y%m%d")
    if source.duplicated(["ts_code", "trade_date"]).any():
        raise ValueError("duplicate stock-day keys in effective-day source")
    market_dates = pd.Index(sorted(source["trade_date"].unique()))
    date_number = pd.Series(np.arange(len(market_dates)), index=market_dates)
    source["market_day_number"] = source["trade_date"].map(date_number).astype(int)
    source = source.sort_values(["ts_code", "market_day_number"])
    counts = np.empty(len(source), dtype=np.int16)
    for positions in source.groupby("ts_code", sort=False).indices.values():
        positions = np.asarray(positions)
        values = source.iloc[positions]["market_day_number"].to_numpy()
        left = np.searchsorted(values, values - 59, side="left")
        counts[positions] = np.arange(len(values)) - left + 1
    source["effective_days_60"] = counts
    lookup = source[["ts_code", "trade_date", "effective_days_60"]]
    output = entries.merge(
        lookup,
        left_on=["ts_code", "entry_date"],
        right_on=["ts_code", "trade_date"],
        how="left",
        validate="one_to_one",
    ).drop(columns=["trade_date"])
    return output


def add_capacity_aware_signals(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"adv20_cny", "size", "l1_code", "signal_date"}
    if missing := required.difference(frame):
        raise ValueError(f"missing C7 signal columns: {sorted(missing)}")
    output = quality_adjusted_value_signal(frame)
    output["liquidity_neutral_signal"] = np.nan
    output["industry_within_signal"] = np.nan
    output["partial_signal"] = np.nan
    for _, month in output.groupby("signal_date", sort=True):
        valid = (
            month["raw_signal"].notna()
            & month["adv20_cny"].gt(0)
            & month["size"].gt(0)
            & month["l1_code"].notna()
        )
        index = month.index[valid]
        if len(index) < 20:
            continue
        y = output.loc[index, "raw_signal"].astype(float)
        y = (y - y.mean()) / y.std(ddof=0)
        log_adv = np.log(output.loc[index, "adv20_cny"].astype(float))
        liquidity_controls = np.column_stack(
            [np.ones(len(index)), (log_adv - log_adv.mean()) / log_adv.std(ddof=0)]
        )
        liquidity_fit = np.linalg.lstsq(liquidity_controls, y, rcond=None)[0]
        output.loc[index, "liquidity_neutral_signal"] = (
            y.to_numpy() - liquidity_controls @ liquidity_fit
        )
        output.loc[index, "industry_within_signal"] = (
            output.loc[index]
            .groupby("l1_code")["raw_signal"]
            .rank(method="average", pct=True)
            .to_numpy()
        )
        log_size = np.log(output.loc[index, "size"].astype(float))
        controls = pd.DataFrame(
            {
                "intercept": 1.0,
                "log_size": (log_size - log_size.mean()) / log_size.std(ddof=0),
                "log_adv": (log_adv - log_adv.mean()) / log_adv.std(ddof=0),
            },
            index=index,
        )
        industries = pd.get_dummies(
            output.loc[index, "l1_code"].astype(str),
            prefix="industry",
            drop_first=True,
            dtype=float,
        )
        controls = pd.concat([controls, industries], axis=1).astype(float)
        fitted = np.linalg.lstsq(controls.to_numpy(), y.to_numpy(), rcond=None)[0]
        output.loc[index, "partial_signal"] = (
            y.to_numpy() - controls.to_numpy() @ fitted
        )
    output.attrs = {}
    return output


def constrained_rank_target(
    candidates: pd.DataFrame,
    benchmark_industry_weights: pd.Series,
    *,
    count: int = 100,
    stock_cap: float = 0.02,
    positive_industry_active_cap: float = 0.05,
) -> pd.Series:
    required = {"ts_code", "l1_code", "raw_signal"}
    if missing := required.difference(candidates):
        raise ValueError(f"missing target columns: {sorted(missing)}")
    ordered = (
        candidates.dropna(subset=["raw_signal", "l1_code"])
        .sort_values(["raw_signal", "ts_code"], ascending=[False, True])
        .head(count)
        .reset_index(drop=True)
    )
    if len(ordered) != count:
        raise ValueError(f"need {count} investable candidates, got {len(ordered)}")
    rank_points = np.arange(count, 0, -1, dtype=float)
    raw_weights = rank_points / rank_points.sum()
    industries = ordered["l1_code"].astype(str).to_numpy()
    constraints: list[dict[str, object]] = [
        {"type": "eq", "fun": lambda weights: float(weights.sum() - 1.0)}
    ]
    for industry in sorted(set(industries)):
        mask = industries == industry
        limit = float(benchmark_industry_weights.get(industry, 0.0)) + positive_industry_active_cap
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda weights, mask=mask, limit=limit: float(
                    limit - weights[mask].sum()
                ),
            }
        )
    result = minimize(
        lambda weights: float(np.square(weights - raw_weights).sum()),
        np.full(count, 1.0 / count),
        method="SLSQP",
        bounds=[(0.0, stock_cap)] * count,
        constraints=constraints,
        options={"ftol": 1e-12, "maxiter": 1000},
    )
    if not result.success:
        raise ValueError(f"capacity-aware target infeasible: {result.message}")
    weights = pd.Series(result.x, index=ordered["ts_code"], dtype=float)
    weights[weights.abs() < 1e-12] = 0.0
    weights /= weights.sum()
    return weights


def square_root_impact_cost(
    trade_weight: pd.Series,
    adv20_cny: pd.Series,
    *,
    capital_cny: float = 10_000_000.0,
    reference_participation: float = 0.02,
    impact_at_reference: float = 0.001,
) -> tuple[float, pd.Series]:
    aligned_adv = adv20_cny.reindex(trade_weight.index)
    valid_adv = aligned_adv.gt(0) & aligned_adv.notna()
    participation = capital_cny * trade_weight.abs() / aligned_adv.where(valid_adv)
    impact_rate = impact_at_reference * np.sqrt(
        participation.clip(lower=0.0) / reference_participation
    )
    # Missing ADV is a hard gate failure, but must not poison all performance
    # arithmetic with infinity. Charge the registered cap-rate provisionally and
    # preserve NaN participation so the caller fails the capacity gate.
    impact_rate = impact_rate.where(valid_adv, impact_at_reference)
    cost = 0.5 * float((trade_weight.abs() * impact_rate).sum())
    return cost, participation


def monthly_signal_diagnostics(
    signals: pd.DataFrame,
    labels: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    keys = ["ts_code", "signal_date"]
    merged = signals.merge(
        labels[
            [
                *keys,
                "entry_tradable",
                "exit_6m_tradable",
                "forward_return_6m",
            ]
        ],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_label"),
    )
    entry = (
        merged["entry_tradable"]
        if "entry_tradable" in merged
        else merged["entry_tradable_label"]
    )
    sample = merged[
        merged["investable_c7"].fillna(False)
        & entry.fillna(False)
        & merged["exit_6m_tradable"].fillna(False)
        & merged["forward_return_6m"].notna()
        & merged["partial_signal"].notna()
    ].copy()
    rows: list[dict[str, object]] = []
    for signal_date, month in sample.groupby("signal_date", sort=True):
        try:
            liquidity_layer = pd.qcut(
                month["adv20_cny"].rank(method="first"), 3, labels=[1, 2, 3]
            )
        except ValueError:
            continue
        row: dict[str, object] = {
            "signal_date": signal_date,
            "partial_rank_ic_6m": month["partial_signal"].corr(
                month["forward_return_6m"], method="spearman"
            ),
        }
        for layer in (1, 2, 3):
            part = month[liquidity_layer.astype(int).eq(layer)]
            row[f"raw_rank_ic_6m_liquidity_{layer}"] = part["raw_signal"].corr(
                part["forward_return_6m"], method="spearman"
            )
        rows.append(row)
    monthly = pd.DataFrame(rows)
    summary = {
        "rows": int(len(sample)),
        "months": int(len(monthly)),
        "partial_rank_ic_6m": float(monthly["partial_rank_ic_6m"].mean()),
        "positive_ic_month_share": float(monthly["partial_rank_ic_6m"].gt(0).mean()),
        "middle_liquidity_rank_ic_6m": float(
            monthly["raw_rank_ic_6m_liquidity_2"].mean()
        ),
        "highest_liquidity_rank_ic_6m": float(
            monthly["raw_rank_ic_6m_liquidity_3"].mean()
        ),
    }
    return monthly, summary
