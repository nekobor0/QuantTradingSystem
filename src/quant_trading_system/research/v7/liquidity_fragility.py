"""Liquidity-fragility signal primitives for B7."""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_liquidity_fragility(
    adjusted_return: pd.Series,
    amount_cny: pd.Series,
    market_return: pd.Series,
) -> pd.DataFrame:
    data = pd.concat(
        [
            adjusted_return.rename("return"),
            amount_cny.rename("amount_cny"),
            market_return.rename("market_return"),
        ],
        axis=1,
    ).sort_index()
    illiquidity = data["return"].abs() / data["amount_cny"].replace(0, np.nan)
    amihud20 = illiquidity.rolling(20, min_periods=15).mean()
    amihud252 = illiquidity.rolling(252, min_periods=120).mean()
    amount20 = data["amount_cny"].rolling(20, min_periods=15).mean()
    amount60 = data["amount_cny"].rolling(60, min_periods=40).mean()
    total_volatility = data["return"].rolling(60, min_periods=40).std()
    down_return = data["return"].where(data["market_return"].lt(0))
    down_volatility = down_return.rolling(60, min_periods=10).std()
    output = pd.DataFrame(index=data.index)
    output["amihud_abnormal"] = np.log(amihud20 / amihud252)
    output["amount_contraction"] = -np.log(amount20 / amount60)
    output["down_vol_amplification"] = down_volatility / total_volatility
    output["total_observations_60"] = data["return"].rolling(60).count()
    output["down_observations_60"] = down_return.rolling(60).count()
    return output.replace([np.inf, -np.inf], np.nan)


def cross_sectional_fragility(
    frame: pd.DataFrame,
    *,
    eligible_column: str = "eligible_signal",
) -> pd.DataFrame:
    components = [
        "amihud_abnormal",
        "amount_contraction",
        "down_vol_amplification",
    ]
    required = {
        "signal_date",
        "l1_code",
        "size",
        "beta",
        eligible_column,
        *components,
    }
    if missing := required.difference(frame):
        raise ValueError(f"missing B7 columns: {sorted(missing)}")
    output = frame.copy()
    z_columns = [f"{name}_z" for name in components]
    for column in [*z_columns, "fragility_composite", "defensive_score", "partial_signal"]:
        output[column] = np.nan
    for _, month in output.groupby("signal_date", sort=True):
        valid = (
            month[eligible_column].fillna(False)
            & month[components].notna().all(axis=1)
            & month["l1_code"].notna()
            & month["size"].gt(0)
            & month["beta"].notna()
        )
        index = month.index[valid]
        if len(index) < 20:
            continue
        for source, target in zip(components, z_columns):
            values = output.loc[index, source].astype(float)
            lower, upper = values.quantile([0.01, 0.99])
            values = values.clip(lower, upper)
            scale = values.std(ddof=0)
            output.loc[index, target] = (
                (values - values.mean()) / scale if scale > 0 else np.nan
            )
        composite = output.loc[index, z_columns].mean(axis=1)
        output.loc[index, "fragility_composite"] = composite
        output.loc[index, "defensive_score"] = -composite

        log_size = np.log(output.loc[index, "size"].astype(float))
        beta = output.loc[index, "beta"].astype(float)
        controls = pd.DataFrame(
            {
                "intercept": 1.0,
                "log_size": (log_size - log_size.mean()) / log_size.std(ddof=0),
                "beta": (beta - beta.mean()) / beta.std(ddof=0),
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
        y = output.loc[index, "defensive_score"].astype(float)
        coefficients = np.linalg.lstsq(
            controls.to_numpy(), y.to_numpy(), rcond=None
        )[0]
        output.loc[index, "partial_signal"] = (
            y.to_numpy() - controls.to_numpy() @ coefficients
        )
    output.attrs = {}
    return output
