import pandas as pd

from quant_trading_system.research.alpha_phase1.short_horizon import calculate_short_signals
from quant_trading_system.research.v6.bottom_reversal import (
    attach_pit_survival,
    detect_limit_down_reopen,
)


def test_event_requires_two_sealed_days_and_recovery() -> None:
    daily = pd.DataFrame(
        {
            "open": [10.0, 9.0, 8.1, 7.29, 6.56, 6.56],
            "high": [10.0, 9.0, 8.1, 7.29, 6.56, 6.8],
            "low": [10.0, 9.0, 8.1, 7.29, 6.56, 6.56],
            "close": [10.0, 9.0, 8.1, 7.29, 6.56, 6.7],
            "down_limit": [9.0, 9.0, 8.1, 7.29, 6.56, 6.56],
        },
        index=pd.date_range("2024-01-01", periods=6),
    )
    detected = detect_limit_down_reopen(daily)
    assert detected.sum() == 1
    assert detected.iloc[-1]
    labeled = calculate_short_signals(
        daily.assign(volume=1.0, factor=1.0).reset_index(names="date")
    )
    assert pd.Timestamp("2024-01-06") in labeled.index


def test_touch_without_half_percent_recovery_is_not_event() -> None:
    daily = pd.DataFrame(
        {
            "open": [8.1, 7.29, 6.56],
            "high": [8.1, 7.29, 6.58],
            "low": [8.1, 7.29, 6.56],
            "close": [8.1, 7.29, 6.58],
            "down_limit": [8.1, 7.29, 6.56],
        },
        index=pd.date_range("2024-01-01", periods=3),
    )
    assert not detect_limit_down_reopen(daily).any()


def test_pit_survival_never_uses_future_month() -> None:
    events = pd.DataFrame({"ts_code": ["A"], "signal_date": [pd.Timestamp("2024-04-15")]})
    fundamentals = pd.DataFrame(
        {
            "ts_code": ["A", "A"],
            "signal_date": pd.to_datetime(["2024-03-31", "2024-04-30"]),
            "baseline_quality_z": [0.0, 2.0],
            "is_st": [False, False],
            "delist_date": [pd.NaT, pd.NaT],
            "l1_code": ["I", "I"],
        }
    )
    result = attach_pit_survival(events, fundamentals)
    assert result.loc[0, "fundamental_date"] == pd.Timestamp("2024-03-31")
    assert result.loc[0, "pit_survival"]
