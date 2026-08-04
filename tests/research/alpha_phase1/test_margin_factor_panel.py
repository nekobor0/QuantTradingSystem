from __future__ import annotations

import pandas as pd

from scripts.alpha_phase1.build_margin_factor_panel import build_daily


def test_margin_windows_are_computed_before_month_end_sampling() -> None:
    dates = pd.bdate_range("2024-01-01", periods=21)
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 21,
            "trade_date": dates.strftime("%Y%m%d"),
            "rzye": [100.0 + number for number in range(21)],
            "rzmre": [3.0] * 21,
            "rzche": [2.0] * 21,
        }
    )

    result = build_daily(frame).iloc[-1]

    assert result["net_flow_5"] == 5.0
    assert result["net_flow_10"] == 10.0
    assert result["net_flow_20"] == 20.0
    assert result["margin_flow_acceleration_5_20_raw"] == 0.0
    assert result["balance_change_20"] == 20.0


def test_implausible_repayment_does_not_pollute_rolling_flow() -> None:
    dates = pd.bdate_range("2024-01-01", periods=6)
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 6,
            "trade_date": dates.strftime("%Y%m%d"),
            "rzye": [100.0] * 6,
            "rzmre": [3.0] * 6,
            "rzche": [2.0, 2.0, 2.0, 10_000.0, 2.0, 2.0],
        }
    )

    result = build_daily(frame)

    assert pd.isna(result.loc[3, "net_margin_flow"])
    assert result.iloc[-1]["net_flow_5"] == 4.0
