"""Preregistered Lane A index-enhancement research utilities."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import STYLE_COMPONENTS


def _positive_normalized(values: pd.Series) -> pd.Series:
    clean = values.clip(lower=0.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if float(clean.sum()) <= 0:
        return pd.Series(1.0 / len(clean), index=clean.index)
    return clean / clean.sum()


def shrunken_icir_weights(
    ic_history: pd.DataFrame,
    *,
    prior_months: int = 60,
) -> tuple[pd.Series, float, pd.Series]:
    """Shrink non-negative expanding ICIR weights toward equal weights."""
    if prior_months <= 0:
        raise ValueError("prior_months must be positive")
    if ic_history.empty:
        raise ValueError("ic_history must not be empty")
    raw_icir = ic_history.mean() / ic_history.std(ddof=1)
    empirical = _positive_normalized(raw_icir)
    equal = pd.Series(1.0 / len(empirical), index=empirical.index)
    shrinkage = len(ic_history) / (len(ic_history) + prior_months)
    weights = shrinkage * empirical + (1.0 - shrinkage) * equal
    return weights / weights.sum(), float(shrinkage), raw_icir


def build_shrunken_icir_scores(
    panel: pd.DataFrame,
    *,
    component_columns: tuple[str, ...] = STYLE_COMPONENTS,
    minimum_history_months: int = 24,
    prior_months: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the preregistered expanding shrunken-ICIR score without leakage."""
    required = {"signal_date", "exit_date", "mark_return_1m", *component_columns}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"missing shrunken ICIR columns: {sorted(missing)}")

    output = panel.copy()
    output["signal_date"] = pd.to_datetime(output["signal_date"])
    output["exit_date"] = pd.to_datetime(output["exit_date"])
    components = list(component_columns)
    monthly_rows: list[dict[str, object]] = []
    for signal_date, month in output.groupby("signal_date", sort=True):
        valid = month["mark_return_1m"].notna()
        if int(valid.sum()) < len(components) + 2:
            continue
        x = month.loc[valid, components].astype(float)
        y = month.loc[valid, "mark_return_1m"].astype(float)
        monthly_rows.append(
            {
                "signal_date": signal_date,
                "exit_date": month.loc[valid, "exit_date"].max(),
                **{f"ic::{name}": x[name].corr(y, method="spearman") for name in components},
            }
        )
    statistics = pd.DataFrame(monthly_rows).sort_values("signal_date")
    output["shrunken_icir_v6_score"] = np.nan
    equal = pd.Series(1.0 / len(components), index=components)
    audits: list[dict[str, object]] = []
    for signal_date in sorted(output["signal_date"].unique()):
        available = statistics[statistics["exit_date"].le(signal_date)]
        if len(available) >= minimum_history_months:
            history = available[[f"ic::{name}" for name in components]].copy()
            history.columns = components
            weights, shrinkage, raw_icir = shrunken_icir_weights(
                history, prior_months=prior_months
            )
        else:
            weights = equal
            shrinkage = 0.0
            raw_icir = pd.Series(np.nan, index=components)
        current = output["signal_date"].eq(signal_date)
        output.loc[current, "shrunken_icir_v6_score"] = (
            output.loc[current, components].fillna(0.0).dot(weights)
        )
        audits.append(
            {
                "signal_date": signal_date,
                "history_months": int(len(available)),
                "latest_used_signal_date": (
                    available["signal_date"].max() if len(available) else pd.NaT
                ),
                "latest_used_exit_date": (
                    available["exit_date"].max() if len(available) else pd.NaT
                ),
                "shrinkage": shrinkage,
                **{f"raw_icir_{name}": float(raw_icir[name]) for name in components},
                **{f"weight_{name}": float(weights[name]) for name in components},
            }
        )
    return output, pd.DataFrame(audits)
