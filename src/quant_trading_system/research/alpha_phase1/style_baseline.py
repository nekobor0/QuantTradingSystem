"""Point-in-time style controls used by the Phase-1 V4 evaluator."""

from __future__ import annotations

import numpy as np
import pandas as pd


def winsorized_zscore(values: pd.Series) -> pd.Series:
    """Cross-sectional 1/99 winsorized z-score, preserving missing values."""
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().astype(float)
    if valid.empty:
        return result
    low, high = valid.quantile([0.01, 0.99])
    clipped = valid.clip(low, high)
    scale = clipped.std(ddof=0)
    result.loc[valid.index] = (
        (clipped - clipped.mean()) / scale if scale and np.isfinite(scale) else 0.0
    )
    return result


def nonlinear_size_residual(size: pd.Series, industry: pd.Series) -> pd.Series:
    """Residualize squared size on linear size and industry dummies."""
    result = pd.Series(np.nan, index=size.index, dtype=float)
    valid = size.notna() & industry.notna()
    if valid.sum() < 10:
        return result
    sample_size = winsorized_zscore(size.loc[valid])
    y = sample_size.pow(2)
    dummies = pd.get_dummies(industry.loc[valid], drop_first=True, dtype=float)
    x = np.column_stack([np.ones(valid.sum()), sample_size.to_numpy(), dummies.to_numpy()])
    result.loc[valid] = y.to_numpy() - x @ np.linalg.lstsq(x, y.to_numpy(), rcond=None)[0]
    return result


def industry_standardize(values: pd.Series, industry: pd.Series) -> pd.Series:
    """Standardize within industry, falling back to the full cross-section for tiny groups."""
    result = pd.Series(np.nan, index=values.index, dtype=float)
    for _, indices in industry.groupby(industry, dropna=False).groups.items():
        valid = values.loc[indices].dropna()
        if len(valid) >= 5:
            result.loc[valid.index] = winsorized_zscore(valid)
    missing = values.notna() & result.isna()
    if missing.any():
        result.loc[missing] = winsorized_zscore(values).loc[missing]
    return result


def value_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Build a value composite while keeping loss status outside the E/P ranking."""
    output = pd.DataFrame(index=frame.index)
    output["loss_dummy"] = frame["earnings_yield"].le(0).astype(float)
    profitable_ep = frame["earnings_yield"].where(frame["earnings_yield"] > 0)
    components = {
        "value_ep_z": profitable_ep,
        "value_bp_z": frame["book_to_price"].where(frame["book_to_price"] > 0),
        "value_sp_z": frame["sales_to_price"].where(frame["sales_to_price"] > 0),
        "value_dy_z": frame["dividend_yield"].where(frame["dividend_yield"] >= 0),
    }
    for name, values in components.items():
        output[name] = industry_standardize(values, frame["l1_code"])
    z_columns = list(components)
    enough = output[z_columns].notna().sum(axis=1) >= 3
    output["value_composite"] = output[z_columns].mean(axis=1).where(enough)
    return output


def investment_composite(frame: pd.DataFrame) -> pd.Series:
    """Equal-weight conservative asset and equity growth signals by industry."""
    parts = pd.concat(
        [
            industry_standardize(frame["conservative_asset_growth"], frame["l1_code"]),
            industry_standardize(frame["conservative_equity_growth"], frame["l1_code"]),
        ],
        axis=1,
    )
    return parts.mean(axis=1).where(parts.notna().sum(axis=1) == 2)


def add_cross_sectional_styles(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach monthly styles using the original row indices without apply-index ambiguity."""
    output = frame.copy()
    value_columns = [
        "value_ep_z", "value_bp_z", "value_sp_z", "value_dy_z",
        "value_composite", "loss_dummy",
    ]
    output["nonlinear_size"] = np.nan
    output[value_columns] = np.nan
    output["investment"] = np.nan
    for _, indices in output.groupby("signal_date", sort=False).groups.items():
        sample = output.loc[indices]
        output.loc[indices, "nonlinear_size"] = nonlinear_size_residual(
            sample["size"], sample["l1_code"]
        )
        output.loc[indices, value_columns] = value_components(sample)[value_columns]
        output.loc[indices, "investment"] = investment_composite(sample)
    return output


def rolling_beta(
    stock_return: pd.Series,
    market_return: pd.Series,
    window: int = 252,
    minimum: int = 120,
) -> pd.Series:
    """Rolling stock beta against a supplied point-in-time market return series."""
    aligned = pd.concat(
        [stock_return.rename("stock"), market_return.rename("market")], axis=1
    ).dropna()
    result = pd.Series(np.nan, index=stock_return.index, dtype=float)
    covariance = aligned["stock"].rolling(window, min_periods=minimum).cov(aligned["market"])
    variance = aligned["market"].rolling(window, min_periods=minimum).var()
    result.loc[aligned.index] = covariance / variance.replace(0, np.nan)
    return result


def rolling_beta_and_residual_volatility(
    stock_return: pd.Series,
    market_return: pd.Series,
    beta_window: int = 252,
    beta_minimum: int = 120,
    volatility_window: int = 60,
    volatility_minimum: int = 40,
) -> pd.DataFrame:
    """Rolling market beta and volatility of ex-post market-model residuals."""
    aligned = pd.concat(
        [stock_return.rename("stock"), market_return.rename("market")], axis=1
    ).dropna()
    covariance = aligned["stock"].rolling(beta_window, min_periods=beta_minimum).cov(
        aligned["market"]
    )
    market_variance = aligned["market"].rolling(
        beta_window, min_periods=beta_minimum
    ).var()
    beta = covariance / market_variance.replace(0, np.nan)
    stock_mean = aligned["stock"].rolling(beta_window, min_periods=beta_minimum).mean()
    market_mean = aligned["market"].rolling(beta_window, min_periods=beta_minimum).mean()
    alpha = stock_mean - beta * market_mean
    residual = aligned["stock"] - alpha - beta * aligned["market"]
    residual_volatility = residual.rolling(
        volatility_window, min_periods=volatility_minimum
    ).std()
    return pd.DataFrame({"beta": beta, "residual_volatility": residual_volatility})
