import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_execution import (
    sample_monthly_execution,
)


def test_mark_return_survives_an_untradable_exit():
    dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"])
    daily = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 10.0, 9.0, 8.5],
            "high": [10.0, 10.2, 9.0, 8.5],
            "low": [10.0, 9.8, 9.0, 8.5],
            "close": [10.0, 10.0, 9.0, 8.5],
            "volume": [100, 100, 100, 100],
            "factor": [1.0, 1.0, 1.0, 1.0],
        }
    )
    result = sample_monthly_execution(
        daily,
        [dates[0], dates[2]],
        {dates[0]: dates[1], dates[2]: dates[3]},
        {dates[0]: dates[3]},
    )
    assert np.isclose(result.loc[0, "mark_return_1m"], -0.15)
    assert not result.loc[0, "exit_tradable"]


def test_suspended_exit_uses_last_available_close_for_marking():
    dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-28"])
    daily = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 10.0, 11.0],
            "high": [10.0, 10.2, 11.0],
            "low": [10.0, 9.8, 11.0],
            "close": [10.0, 10.0, 11.0],
            "volume": [100, 100, 100],
            "factor": [1.0, 1.0, 1.0],
        }
    )
    result = sample_monthly_execution(
        daily,
        [dates[0]],
        {dates[0]: dates[1]},
        {dates[0]: pd.Timestamp("2024-03-01")},
    )
    assert np.isclose(result.loc[0, "mark_return_1m"], 0.10)
    assert not result.loc[0, "exit_tradable"]


def test_suspended_entry_and_exit_use_last_close_for_existing_holding_mark():
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-31", "2024-03-15"]),
            "open": [10.0, 11.0],
            "high": [10.0, 11.0],
            "low": [10.0, 11.0],
            "close": [10.0, 11.0],
            "volume": [100, 100],
            "factor": [1.0, 1.0],
        }
    )
    signal = pd.Timestamp("2024-01-31")
    result = sample_monthly_execution(
        daily,
        [signal],
        {signal: pd.Timestamp("2024-02-01")},
        {signal: pd.Timestamp("2024-03-01")},
    )
    assert np.isclose(result.loc[0, "mark_return_1m"], 0.0)
    assert not result.loc[0, "entry_tradable"]
    assert not result.loc[0, "exit_tradable"]
