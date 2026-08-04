"""Preregistered Lane C quality-adjusted-value signal and selection rules."""

from __future__ import annotations

import numpy as np
import pandas as pd


def quality_adjusted_value_signal(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"signal_date", "baseline_value_z", "baseline_quality_z", "size", "l1_code"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing quality-adjusted-value columns: {sorted(missing)}")
    output = frame.copy()
    output["raw_signal"] = output["baseline_value_z"] - (
        -output["baseline_quality_z"]
    ).clip(lower=0.0)

    for column in ("winsorized_signal", "standardized_signal", "neutralized_signal"):
        output[column] = np.nan
    for _, month in output.groupby("signal_date", sort=True):
        valid = month["raw_signal"].notna()
        if int(valid.sum()) < 10:
            continue
        valid_index = month.index[valid]
        lower, upper = output.loc[valid_index, "raw_signal"].quantile([0.01, 0.99])
        output.loc[valid_index, "winsorized_signal"] = output.loc[
            valid_index, "raw_signal"
        ].clip(lower, upper)
        values = output.loc[valid_index, "winsorized_signal"]
        scale = values.std(ddof=0)
        output.loc[valid_index, "standardized_signal"] = (
            (values - values.mean()) / scale if scale > 0 else np.nan
        )
        controls = pd.DataFrame(
            {
                "intercept": 1.0,
                "log_size": np.log(output.loc[valid_index, "size"].clip(lower=1.0)),
            },
            index=valid_index,
        )
        industries = pd.get_dummies(
            output.loc[valid_index, "l1_code"].astype(str), prefix="industry", dtype=float
        )
        controls = pd.concat([controls, industries], axis=1).astype(float)
        y = output.loc[valid_index, "standardized_signal"].astype(float)
        coefficients = np.linalg.pinv(controls.to_numpy()) @ y.to_numpy()
        output.loc[valid_index, "neutralized_signal"] = (
            y.to_numpy() - controls.to_numpy() @ coefficients
        )
    output.attrs = {}
    return output


def select_with_industry_cap(
    ranked: pd.DataFrame,
    *,
    count: int = 30,
    max_per_industry: int = 6,
) -> list[str]:
    required = {"ts_code", "l1_code", "raw_signal"}
    missing = required.difference(ranked.columns)
    if missing:
        raise ValueError(f"missing selection columns: {sorted(missing)}")
    selected: list[str] = []
    industry_counts: dict[str, int] = {}
    ordered = ranked.dropna(subset=["raw_signal", "l1_code"]).sort_values(
        ["raw_signal", "ts_code"], ascending=[False, True]
    )
    for row in ordered.itertuples(index=False):
        industry = str(row.l1_code)
        if industry_counts.get(industry, 0) >= max_per_industry:
            continue
        selected.append(str(row.ts_code))
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        if len(selected) == count:
            break
    return selected
