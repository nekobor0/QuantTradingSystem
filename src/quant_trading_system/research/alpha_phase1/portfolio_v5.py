"""Frozen V5 benchmark-relative portfolio construction and performance metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd


STYLE_COMPONENTS = (
    "baseline_value_z",
    "baseline_quality_z",
    "baseline_investment_z",
    "baseline_momentum_z",
    "baseline_low_resvol_z",
)


def _normalise_positive_weights(values: pd.Series) -> pd.Series:
    weights = values.clip(lower=0.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if float(weights.sum()) <= 0:
        return pd.Series(1.0 / len(values), index=values.index)
    return weights / weights.sum()


def build_adaptive_composite_scores(
    panel: pd.DataFrame,
    component_columns: tuple[str, ...] = STYLE_COMPONENTS,
    minimum_history_months: int = 24,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build expanding ICIR and trailing regression scores without label leakage."""
    required = {
        "signal_date",
        "exit_date",
        "mark_return_1m",
        *component_columns,
    }
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"missing adaptive composite columns: {sorted(missing)}")

    output = panel.copy()
    output["signal_date"] = pd.to_datetime(output["signal_date"])
    output["exit_date"] = pd.to_datetime(output["exit_date"])
    component_names = list(component_columns)
    monthly_statistics: list[dict] = []
    for signal_date, month in output.groupby("signal_date", sort=True):
        valid = month["mark_return_1m"].notna()
        if int(valid.sum()) < len(component_names) + 2:
            continue
        x = month.loc[valid, component_names].fillna(0.0).astype(float)
        y = month.loc[valid, "mark_return_1m"].astype(float)
        x_centered = x - x.mean()
        y_centered = y - y.mean()
        row = {
            "signal_date": signal_date,
            "exit_date": month.loc[valid, "exit_date"].max(),
            "xtx": x_centered.to_numpy().T @ x_centered.to_numpy(),
            "xty": x_centered.to_numpy().T @ y_centered.to_numpy(),
        }
        row.update(
            {
                f"ic::{column}": x[column].corr(y, method="spearman")
                for column in component_names
            }
        )
        monthly_statistics.append(row)

    statistics = pd.DataFrame(monthly_statistics).sort_values("signal_date")
    score_columns = {
        "historical_icir": "style_baseline_historical_icir",
        "rolling_regression_24m": "style_baseline_rolling_regression_24m",
    }
    for score_column in score_columns.values():
        output[score_column] = np.nan
    audit_rows: list[dict] = []
    equal_weights = pd.Series(1.0 / len(component_names), index=component_names)

    for signal_date in sorted(output["signal_date"].unique()):
        available = statistics[statistics["exit_date"].le(signal_date)]
        history_months = len(available)
        if history_months >= minimum_history_months:
            ic_frame = available[[f"ic::{column}" for column in component_names]].copy()
            ic_frame.columns = component_names
            icir = ic_frame.mean() / ic_frame.std(ddof=1)
            icir_weights = _normalise_positive_weights(icir)

            trailing = available.tail(24)
            xtx = np.sum(np.stack(trailing["xtx"].to_list()), axis=0)
            xty = np.sum(np.stack(trailing["xty"].to_list()), axis=0)
            coefficients = pd.Series(np.linalg.pinv(xtx) @ xty, index=component_names)
            regression_weights = _normalise_positive_weights(coefficients)
        else:
            icir_weights = equal_weights
            regression_weights = equal_weights

        current = output["signal_date"].eq(signal_date)
        current_components = output.loc[current, component_names].fillna(0.0)
        output.loc[current, score_columns["historical_icir"]] = current_components.dot(
            icir_weights
        )
        output.loc[current, score_columns["rolling_regression_24m"]] = current_components.dot(
            regression_weights
        )
        for method, weights in (
            ("historical_icir", icir_weights),
            ("rolling_regression_24m", regression_weights),
        ):
            audit_rows.append(
                {
                    "signal_date": signal_date,
                    "method": method,
                    "history_months": history_months,
                    "latest_used_signal_date": (
                        available["signal_date"].max() if history_months else pd.NaT
                    ),
                    **{f"weight_{name}": float(weights[name]) for name in component_names},
                }
            )
    return output, pd.DataFrame(audit_rows)


def construct_industry_rotation_target(
    universe: pd.DataFrame,
    benchmark_weights: pd.Series,
    score_column: str = "style_baseline_equal_weight",
    active_fraction: float = 0.20,
    receiver_count: int = 10,
    stock_cap: float = 0.08,
    size_active_cap: float = 0.25,
    benchmark_size_exposure: float | None = None,
    receiver_addition_cap: pd.Series | None = None,
) -> pd.Series:
    """Rotate benchmark industry weight from low-score names to all-A high-score names."""
    eligible = universe[
        universe[score_column].notna()
        & universe["size_z"].notna()
        & universe["l1_code"].notna()
        & universe["eligible_entry"].astype(bool)
    ].copy()
    eligible = eligible.drop_duplicates("ts_code").set_index("ts_code")
    base = benchmark_weights.reindex(eligible.index).fillna(0.0).clip(lower=0.0)
    if base.sum() <= 0:
        raise ValueError("no eligible benchmark weight")
    base /= base.sum()
    target = base.copy()
    receiver_addition_cap = (
        pd.Series(np.inf, index=eligible.index)
        if receiver_addition_cap is None
        else receiver_addition_cap.reindex(eligible.index).fillna(0.0).clip(lower=0.0)
    )
    added = pd.Series(0.0, index=eligible.index)

    for industry, industry_frame in eligible.groupby("l1_code"):
        names = industry_frame.index
        industry_weight = float(base.reindex(names).sum())
        if industry_weight <= 0:
            continue
        budget = active_fraction * industry_weight
        donors = industry_frame.loc[base.reindex(names).gt(0)].sort_values(score_column).index
        removed = 0.0
        for name in donors:
            amount = min(float(target[name]), budget - removed)
            target[name] -= amount
            removed += amount
            if removed >= budget - 1e-12:
                break
        receivers = industry_frame.sort_values(score_column, ascending=False).head(receiver_count).index
        remaining = removed
        while remaining > 1e-12:
            capacities = pd.concat(
                [
                    (stock_cap - target.reindex(receivers)).clip(lower=0.0),
                    (receiver_addition_cap.reindex(receivers) - added.reindex(receivers)).clip(lower=0.0),
                ],
                axis=1,
            ).min(axis=1)
            available = capacities[capacities > 1e-12]
            if available.empty:
                break
            allocation = min(remaining / len(available), float(available.min()))
            target.loc[available.index] += allocation
            added.loc[available.index] += allocation
            remaining -= allocation * len(available)
        if remaining > 1e-12:
            target.loc[donors] += remaining * base.loc[donors] / base.loc[donors].sum()

    active = target - base
    base_size = float((base * eligible["size_z"]).sum())
    reference_size = base_size if benchmark_size_exposure is None else benchmark_size_exposure
    base_difference = base_size - reference_size
    active_size = float((active * eligible["size_z"]).sum())
    final_difference = base_difference + active_size
    if abs(final_difference) > size_active_cap and active_size != 0:
        boundary = size_active_cap if final_difference > 0 else -size_active_cap
        scale = np.clip((boundary - base_difference) / active_size, 0.0, 1.0)
        target = base + active * scale
    target = repair_size_exposure(
        target,
        eligible,
        reference_size,
        size_active_cap,
        stock_cap,
    )
    target = target.clip(lower=0.0, upper=stock_cap)
    return target / target.sum()


def repair_size_exposure(
    target: pd.Series,
    eligible: pd.DataFrame,
    reference_size: float,
    cap: float,
    stock_cap: float,
    movable: pd.Series | None = None,
    receivable: pd.Series | None = None,
) -> pd.Series:
    """Shift weight between size extremes inside each industry until the cap is met."""
    output = target.copy()
    movable = (
        pd.Series(True, index=eligible.index)
        if movable is None
        else movable.reindex(eligible.index).fillna(False)
    )
    receivable = (
        pd.Series(True, index=eligible.index)
        if receivable is None
        else receivable.reindex(eligible.index).fillna(False)
    )
    difference = float((output * eligible["size_z"]).sum() - reference_size)
    if abs(difference) <= cap:
        return output
    reduce_size = difference > cap
    required = abs(difference) - cap
    for _, industry_frame in eligible.groupby("l1_code"):
        ordered = industry_frame.sort_values("size_z")
        receiver_order = ordered.index if reduce_size else ordered.index[::-1]
        donor_order = ordered.index[::-1] if reduce_size else ordered.index
        receivers = [name for name in receiver_order if bool(receivable.get(name, False))]
        donors = [name for name in donor_order if bool(movable.get(name, False))]
        for donor in donors:
            donor_available = float(output.get(donor, 0.0))
            if donor_available <= 1e-14:
                continue
            for receiver in receivers:
                if receiver == donor:
                    continue
                gap = abs(float(eligible.at[donor, "size_z"] - eligible.at[receiver, "size_z"]))
                if gap <= 1e-14:
                    continue
                receiver_capacity = stock_cap - float(output.get(receiver, 0.0))
                shift = min(donor_available, receiver_capacity, required / gap)
                if shift <= 1e-14:
                    continue
                output[donor] -= shift
                output[receiver] = output.get(receiver, 0.0) + shift
                donor_available -= shift
                required -= shift * gap
                if required <= 1e-12:
                    return output
                if donor_available <= 1e-14:
                    break
    if required > 1e-12:
        ordered = eligible.sort_values("size_z")
        receiver_order = ordered.index if reduce_size else ordered.index[::-1]
        donor_order = ordered.index[::-1] if reduce_size else ordered.index
        receivers = [name for name in receiver_order if bool(receivable.get(name, False))]
        donors = [name for name in donor_order if bool(movable.get(name, False))]
        industry_weight = output.groupby(eligible["l1_code"]).sum()
        for donor in donors:
            donor_available = float(output.get(donor, 0.0))
            if donor_available <= 1e-14:
                continue
            donor_industry = eligible.at[donor, "l1_code"]
            for receiver in receivers:
                if receiver == donor:
                    continue
                receiver_industry = eligible.at[receiver, "l1_code"]
                gap = abs(float(eligible.at[donor, "size_z"] - eligible.at[receiver, "size_z"]))
                if gap <= 1e-14:
                    continue
                receiver_capacity = stock_cap - float(output.get(receiver, 0.0))
                if receiver_industry != donor_industry:
                    receiver_capacity = min(
                        receiver_capacity,
                        0.30 - float(industry_weight.get(receiver_industry, 0.0)),
                    )
                shift = min(donor_available, receiver_capacity, required / gap)
                if shift <= 1e-14:
                    continue
                output[donor] -= shift
                output[receiver] = output.get(receiver, 0.0) + shift
                donor_available -= shift
                required -= shift * gap
                if receiver_industry != donor_industry:
                    industry_weight[donor_industry] -= shift
                    industry_weight[receiver_industry] = (
                        float(industry_weight.get(receiver_industry, 0.0)) + shift
                    )
                if required <= 1e-12:
                    return output
                if donor_available <= 1e-14:
                    break
    return output


def enforce_execution_and_turnover(
    target: pd.Series,
    pretrade: pd.Series,
    can_trade: pd.Series,
    turnover_cap: float = 1.0,
) -> tuple[pd.Series, float]:
    names = target.index.union(pretrade.index)
    target = target.reindex(names).fillna(0.0)
    pretrade = pretrade.reindex(names).fillna(0.0)
    can_trade = can_trade.reindex(names).fillna(False)
    frozen = pretrade.where(~can_trade, 0.0)
    remaining = 1.0 - float(frozen.sum())
    if remaining < -1e-10:
        raise ValueError("frozen holdings exceed total portfolio weight")
    desired = target.where(can_trade, 0.0)
    if desired.sum() > 0:
        actual = frozen + desired / desired.sum() * max(remaining, 0.0)
    else:
        actual = frozen
    if actual.sum() > 0:
        actual /= actual.sum()
    turnover = 0.5 * float((actual - pretrade).abs().sum())
    if turnover > turnover_cap and turnover > 0:
        blend = turnover_cap / turnover
        actual = pretrade + blend * (actual - pretrade)
        actual /= actual.sum()
        turnover = 0.5 * float((actual - pretrade).abs().sum())
    return actual[actual > 1e-14], turnover


def maximum_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min())


def performance_metrics(monthly: pd.DataFrame) -> dict[str, float | int]:
    data = monthly.dropna(subset=["portfolio_net_return", "benchmark_return"]).copy()
    active = data["portfolio_net_return"] - data["benchmark_return"]
    years = len(data) / 12.0
    portfolio_annual = float((1 + data["portfolio_net_return"]).prod() ** (1 / years) - 1)
    benchmark_annual = float((1 + data["benchmark_return"]).prod() ** (1 / years) - 1)
    tracking_error = float(active.std(ddof=1) * np.sqrt(12))
    active_std = float(active.std(ddof=1))
    return {
        "months": int(len(data)),
        "portfolio_annual_return": portfolio_annual,
        "benchmark_annual_return": benchmark_annual,
        "annual_excess_return_difference": portfolio_annual - benchmark_annual,
        "tracking_error": tracking_error,
        "information_ratio": (
            float(active.mean() / active_std * np.sqrt(12)) if active_std > 0 else np.nan
        ),
        "absolute_max_drawdown": maximum_drawdown(data["portfolio_net_return"]),
        "excess_max_drawdown": maximum_drawdown(active),
        "monthly_excess_win_rate": float(active.gt(0).mean()),
        "average_monthly_one_way_turnover": float(data["turnover"].mean()),
        "maximum_monthly_one_way_turnover": float(data["turnover"].max()),
    }
