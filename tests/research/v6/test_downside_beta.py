import numpy as np
import pandas as pd

from quant_trading_system.research.v6.downside_beta import (
    cross_sectional_signal,
    downside_metrics,
    rolling_downside_beta,
)


def test_rolling_downside_beta_recovers_known_slope() -> None:
    dates = pd.date_range("2020-01-01", periods=300, freq="D")
    market = pd.Series(np.tile([-0.01, 0.005, -0.02], 100), index=dates)
    stock = 0.6 * market + 0.001
    result = rolling_downside_beta(stock, market, min_down_observations=30)
    assert result["downside_beta"].dropna().iloc[-1] == pytest.approx(0.6)
    assert result["down_observations"].iloc[-1] >= 30


def test_appending_future_returns_does_not_change_historical_signal() -> None:
    dates = pd.date_range("2020-01-01", periods=320, freq="D")
    market = pd.Series(np.sin(np.arange(320)) / 100, index=dates)
    stock = 0.7 * market + np.cos(np.arange(320)) / 1000
    original = rolling_downside_beta(stock.iloc[:300], market.iloc[:300])
    extended = rolling_downside_beta(stock, market)
    pd.testing.assert_series_equal(
        original["downside_beta"],
        extended.loc[original.index, "downside_beta"],
    )


def test_cross_sectional_signal_reverses_direction() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2024-01-31"] * 4),
            "downside_beta": [0.2, 0.5, 0.8, 1.1],
        }
    )
    result = cross_sectional_signal(frame)
    assert result.loc[0, "standardized_signal"] > result.loc[3, "standardized_signal"]
    assert result["raw_signal"].equals(frame["downside_beta"])


def test_cross_sectional_signal_excludes_ineligible_rows_from_transform() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2024-01-31"] * 4),
            "downside_beta": [0.2, 0.5, 0.8, 100.0],
            "eligible": [True, True, True, False],
        }
    )
    result = cross_sectional_signal(frame, eligible="eligible")
    assert pd.isna(result.loc[3, "standardized_signal"])
    assert result.loc[3, "raw_signal"] == 100.0


def test_downside_metrics_uses_only_negative_benchmark_months() -> None:
    monthly = pd.DataFrame(
        {
            "signal_date": pd.date_range("2024-01-31", periods=4, freq="ME"),
            "portfolio_net_return": [-0.01, 0.03, -0.02, 0.01],
            "benchmark_return": [-0.02, 0.02, -0.04, 0.01],
        }
    )
    metrics = downside_metrics(monthly)
    assert metrics["down_months"] == 2
    assert metrics["down_month_mean_active_return"] == pytest.approx(0.015)
    assert metrics["downside_beta"] == pytest.approx(0.5)


import pytest
