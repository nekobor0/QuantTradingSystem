from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.event_evaluation import (
    identify_first_sealed_limit_up,
    keep_events_after_cooldown,
    map_to_effective_trading_date,
    summarize_matched_events,
)


def test_first_sealed_limit_up_excludes_consecutive_seals() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": pd.bdate_range("2024-01-01", periods=5),
            "close": [10.0, 11.0, 12.1, 11.5, 12.65],
            "up_limit": [11.0, 11.0, 12.1, 13.31, 12.65],
            "volume": 100,
        }
    )

    result = identify_first_sealed_limit_up(frame)

    assert result.tolist() == [False, True, False, False, True]


def test_first_sealed_limit_up_requires_close_at_official_limit() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": pd.bdate_range("2024-01-01", periods=2),
            "close": [10.99, 11.00],
            "up_limit": [11.00, 11.00],
            "volume": 100,
        }
    )

    result = identify_first_sealed_limit_up(frame)

    assert result.tolist() == [False, True]


def test_matched_event_attribution_uses_daily_event_portfolios() -> None:
    events = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03"]),
            "matched_car_5": [0.01, 0.02, 0.015],
            "market_car_5": [0.012, 0.024, 0.018],
        }
    )

    result = summarize_matched_events(events, 5)

    assert result["events"] == 3
    assert result["event_days"] == 2
    assert np.isclose(result["event_specific_share"], 5 / 6)
    assert np.isclose(result["style_share"], 1 / 6)


def test_announcement_maps_to_same_or_next_trading_date() -> None:
    calendar = pd.DatetimeIndex(["2024-01-05", "2024-01-08", "2024-01-09"])
    announcements = pd.Series(pd.to_datetime(["2024-01-05", "2024-01-06", "2024-01-10"]))

    result = map_to_effective_trading_date(announcements, calendar)

    assert result.iloc[0] == pd.Timestamp("2024-01-05")
    assert result.iloc[1] == pd.Timestamp("2024-01-08")
    assert pd.isna(result.iloc[2])


def test_same_stock_event_cooldown_is_calendar_day_based() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000001.SZ", "000002.SZ"],
            "signal_date": pd.to_datetime(["2024-01-01", "2024-01-20", "2024-02-01", "2024-01-20"]),
        }
    )

    result = keep_events_after_cooldown(frame, 30)

    assert result.tolist() == [True, False, False, True]
