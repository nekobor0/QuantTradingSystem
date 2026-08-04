from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.short_horizon import calculate_short_signals


def _bars(rows: int = 300) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=rows)
    close = pd.Series(100 * 1.001 ** np.arange(rows))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.arange(rows) + 1000,
            "factor": 1.0,
        }
    )


def test_short_label_enters_next_open_and_exits_frozen_five_day_close() -> None:
    bars = _bars()
    bars.loc[101, "open"] = bars.loc[101, "close"] * 0.99
    result = calculate_short_signals(bars)
    expected = bars.loc[106, "close"] / bars.loc[101, "open"] - 1

    assert np.isclose(result.iloc[100]["forward_return_5"], expected)


def test_untradable_exit_invalidates_short_label() -> None:
    bars = _bars()
    bars.loc[106, ["open", "high", "low", "close"]] = bars.loc[105, "close"] * 1.1
    result = calculate_short_signals(bars)

    assert pd.isna(result.iloc[100]["forward_return_5"])
