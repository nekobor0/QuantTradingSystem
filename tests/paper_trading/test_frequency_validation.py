from __future__ import annotations

import pandas as pd
import pytest

from paper_trading.frequency_validation import _select
from paper_trading.tax_lot_validation import _position_schedule


def test_position_schedule_keeps_daily_values() -> None:
    raw = pd.Series([1.0, 0.8, 0.4, 0.0])
    assert _position_schedule(raw, [0, 2], "daily").tolist() == raw.tolist()


def test_position_schedule_holds_value_between_monthly_entries() -> None:
    raw = pd.Series([1.0, 0.8, 0.4, 0.2, 0.0])
    assert _position_schedule(raw, [1, 4], "monthly").tolist() == [1.0, 0.8, 0.8, 0.8, 0.0]


def test_position_schedule_rejects_unknown_frequency() -> None:
    with pytest.raises(ValueError, match="unsupported position frequency"):
        _position_schedule(pd.Series([1.0]), [0], "weekly")


def test_selection_requires_all_daily_hurdles() -> None:
    scenarios = {
        "both_monthly": {"sharpe": 1.0, "annualized_return": 0.15, "max_drawdown": -0.20},
        "dividend_monthly_voltrend_daily": {
            "sharpe": 1.06,
            "annualized_return": 0.16,
            "max_drawdown": -0.21,
        },
    }
    assert _select(scenarios)[0] == "dividend_monthly_voltrend_daily"
    scenarios["dividend_monthly_voltrend_daily"]["annualized_return"] = 0.14
    assert _select(scenarios)[0] == "both_monthly"
