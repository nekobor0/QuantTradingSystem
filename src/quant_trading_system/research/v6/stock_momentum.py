"""Preregistered Lane E industry-residual momentum signal."""

from __future__ import annotations

import numpy as np
import pandas as pd


CONTROLS = ("size", "beta", "residual_volatility", "l1_code")


def industry_residual_momentum(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"signal_date", "momentum", *CONTROLS}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing residual momentum columns: {sorted(missing)}")
    output = frame.copy()
    output["raw_signal"] = output["momentum"]
    for column in ("winsorized_signal", "standardized_signal", "neutralized_signal"):
        output[column] = np.nan
    for _, month in output.groupby("signal_date", sort=True):
        valid = month[["raw_signal", *CONTROLS]].notna().all(axis=1)
        if int(valid.sum()) < 20:
            continue
        index = month.index[valid]
        lower, upper = output.loc[index, "raw_signal"].quantile([0.01, 0.99])
        output.loc[index, "winsorized_signal"] = output.loc[index, "raw_signal"].clip(lower, upper)
        values = output.loc[index, "winsorized_signal"]
        scale = values.std(ddof=0)
        output.loc[index, "standardized_signal"] = (values - values.mean()) / scale
        controls = pd.DataFrame(
            {
                "intercept": 1.0,
                "log_size": np.log(output.loc[index, "size"].clip(lower=1.0)),
                "beta": output.loc[index, "beta"],
                "residual_volatility": output.loc[index, "residual_volatility"],
            },
            index=index,
        )
        industries = pd.get_dummies(
            output.loc[index, "l1_code"].astype(str), prefix="industry", dtype=float
        )
        controls = pd.concat([controls, industries], axis=1).astype(float)
        y = output.loc[index, "standardized_signal"].to_numpy(dtype=float)
        x = controls.to_numpy(dtype=float)
        output.loc[index, "neutralized_signal"] = y - x @ (np.linalg.pinv(x) @ y)
    output.attrs = {}
    return output
