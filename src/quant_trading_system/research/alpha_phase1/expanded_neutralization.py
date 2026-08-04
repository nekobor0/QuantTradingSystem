"""Expanded V4 cross-sectional neutralization for candidate Alpha factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.style_baseline import winsorized_zscore


EXPANDED_CONTROLS = [
    "size", "nonlinear_size", "beta", "momentum", "short_reversal", "liquidity",
    "residual_volatility", "value_composite", "investment", "quality_composite",
    "leverage", "loss_dummy",
]


def neutralize_expanded(frame: pd.DataFrame, factor: str) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, indices in frame.groupby("signal_date", sort=False).groups.items():
        valid = (
            frame.loc[indices, "eligible_evaluation"]
            & frame.loc[indices, factor].notna()
            & frame.loc[indices, EXPANDED_CONTROLS + ["l1_code"]].notna().all(axis=1)
        )
        sample_indices = pd.Index(indices)[valid.to_numpy()]
        if len(sample_indices) < 100:
            continue
        y = frame.loc[sample_indices, factor]
        y = y.clip(*y.quantile([0.01, 0.99])).rank(pct=True)
        numeric = np.column_stack(
            [
                winsorized_zscore(frame.loc[sample_indices, column]).to_numpy()
                for column in EXPANDED_CONTROLS
            ]
        )
        industries = pd.get_dummies(
            frame.loc[sample_indices, "l1_code"], drop_first=True, dtype=float
        ).to_numpy()
        x = np.column_stack([np.ones(len(sample_indices)), numeric, industries])
        result.loc[sample_indices] = y.to_numpy() - x @ np.linalg.lstsq(
            x, y.to_numpy(), rcond=None
        )[0]
    return result
