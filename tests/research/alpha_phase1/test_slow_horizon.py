import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.slow_horizon import (
    horizon_dates,
    sample_slow_labels,
)


def test_slow_label_enters_at_next_open_and_exits_at_future_close():
    dates = pd.bdate_range("2024-01-30", periods=8)
    signals = [dates[1], dates[4], dates[6]]
    entry, exits = horizon_dates(list(dates), signals, horizons=(1,))
    daily = pd.DataFrame(
        {
            "date": dates,
            "open": [10, 10, 20, 10, 10, 10, 10, 10],
            "high": [11] * 8,
            "low": [9] * 8,
            "close": [10, 10, 99, 10, 10, 30, 10, 40],
            "volume": [100] * 8,
            "factor": [1] * 8,
        }
    )
    result = sample_slow_labels(daily, signals, entry, exits)
    assert np.isclose(result.loc[0, "forward_return_1m"], 30 / 20 - 1)
    assert np.isclose(result.loc[1, "forward_return_1m"], 40 / 10 - 1)
    assert np.isnan(result.loc[2, "forward_return_1m"])
