from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.alpha_phase1.build_factor_panel import sample_symbol


def _daily(entry_close: float, entry_ohlc: tuple[float, float, float, float]) -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"])
    open_, high, low, close = zip(
        (10.0, 10.2, 9.8, 10.0),
        entry_ohlc,
        (entry_close, entry_close * 1.01, entry_close * 0.99, entry_close),
        (entry_close, entry_close * 1.01, entry_close * 0.99, entry_close),
    )
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [100.0] * 4,
            "amount": [1000.0] * 4,
            "factor": [1.0] * 4,
        }
    )


def test_t_plus_one_label_rejects_one_price_limit_entry() -> None:
    signal = pd.Timestamp("2024-01-31")
    exit_date = pd.Timestamp("2024-03-01")
    entry_date = pd.Timestamp("2024-02-01")
    daily = _daily(11.0, (11.0, 11.0, 11.0, 11.0))

    panel = sample_symbol(
        "600000.SH",
        daily,
        [signal],
        {signal: entry_date},
        {signal: exit_date},
        {},
        {},
    )

    assert not bool(panel.loc[0, "entry_1_tradable"])
    assert np.isnan(panel.loc[0, "forward_return"])


def test_t_plus_one_label_uses_open_for_traded_entry() -> None:
    signal = pd.Timestamp("2024-01-31")
    exit_date = pd.Timestamp("2024-03-01")
    entry_date = pd.Timestamp("2024-02-01")
    daily = _daily(10.5, (10.4, 10.6, 10.3, 10.5))

    panel = sample_symbol(
        "600000.SH",
        daily,
        [signal],
        {signal: entry_date},
        {signal: exit_date},
        {},
        {},
    )

    assert bool(panel.loc[0, "entry_1_tradable"])
    assert np.isclose(panel.loc[0, "forward_return"], 10.5 / 10.4 - 1)
