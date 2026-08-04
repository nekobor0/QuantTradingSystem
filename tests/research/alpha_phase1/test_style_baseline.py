import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.style_baseline import (
    add_cross_sectional_styles,
    nonlinear_size_residual,
    rolling_beta,
    rolling_beta_and_residual_volatility,
    value_components,
    winsorized_zscore,
)


def test_winsorized_zscore_preserves_missing_and_centers_values():
    values = pd.Series([1.0, 2.0, 3.0, np.nan, 1000.0])
    result = winsorized_zscore(values)
    assert np.isclose(result.dropna().mean(), 0.0)
    assert np.isclose(result.dropna().std(ddof=0), 1.0)
    assert np.isnan(result.iloc[3])


def test_nonlinear_size_is_orthogonal_to_linear_size_and_industry():
    size = pd.Series(np.linspace(-2, 2, 40))
    industry = pd.Series(["a"] * 20 + ["b"] * 20)
    residual = nonlinear_size_residual(size, industry).dropna()
    standardized = winsorized_zscore(size).loc[residual.index]
    assert abs(residual.corr(standardized)) < 1e-10
    assert abs(residual.groupby(industry.loc[residual.index]).mean()).max() < 1e-10


def test_value_composite_does_not_mix_losses_into_ep_rank():
    frame = pd.DataFrame(
        {
            "earnings_yield": [-0.1, 0.05, 0.10, 0.15, 0.20, 0.25],
            "book_to_price": [1, 2, 3, 4, 5, 6],
            "sales_to_price": [1, 2, 3, 4, 5, 6],
            "dividend_yield": [0, 1, 2, 3, 4, 5],
            "l1_code": ["a"] * 6,
        }
    )
    output = value_components(frame)
    assert output.loc[0, "loss_dummy"] == 1
    assert np.isnan(output.loc[0, "value_ep_z"])
    assert output.loc[1:, "value_ep_z"].notna().all()


def test_rolling_beta_recovers_known_slope():
    market = pd.Series(np.sin(np.arange(300) / 10), index=pd.date_range("2020-01-01", periods=300))
    stock = 1.5 * market
    result = rolling_beta(stock, market)
    assert np.isclose(result.dropna().iloc[-1], 1.5)


def test_residual_volatility_is_zero_for_exact_market_model():
    index = pd.date_range("2020-01-01", periods=300)
    market = pd.Series(np.sin(np.arange(300) / 10), index=index)
    stock = 0.01 + 1.5 * market
    result = rolling_beta_and_residual_volatility(stock, market)
    assert np.isclose(result["beta"].dropna().iloc[-1], 1.5)
    assert result["residual_volatility"].dropna().iloc[-1] < 1e-12


def test_cross_sectional_styles_stay_on_original_rows():
    rows = []
    for date in pd.to_datetime(["2024-01-31", "2024-02-29"]):
        for number in range(12):
            rows.append(
                {
                    "signal_date": date,
                    "size": float(number),
                    "l1_code": "a" if number < 6 else "b",
                    "earnings_yield": 0.01 + number / 100,
                    "book_to_price": 1.0 + number,
                    "sales_to_price": 2.0 + number,
                    "dividend_yield": number / 100,
                    "conservative_asset_growth": -number / 10,
                    "conservative_equity_growth": -number / 20,
                }
            )
    frame = pd.DataFrame(rows, index=np.arange(100, 124) * 3)
    output = add_cross_sectional_styles(frame)
    assert output.index.equals(frame.index)
    assert output["nonlinear_size"].notna().all()
    assert output["value_composite"].notna().all()
    assert output["investment"].notna().all()
