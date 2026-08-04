import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.fundamental_surprise import (
    announcement_returns,
    monthly_point_in_time,
    prepare_versions,
)


def test_previous_quarter_uses_only_version_known_at_current_announcement():
    raw = pd.DataFrame(
        {
            "ts_code": ["A", "A", "A"],
            "ann_date": ["20240420", "20240501", "20240820"],
            "end_date": ["20240331", "20240331", "20240630"],
            "update_flag": [0, 1, 0],
            "q_profit_yoy": [10.0, 30.0, 50.0],
            "q_sales_yoy": [5.0, 6.0, 8.0],
            "ocf_to_or": [1.0, 2.0, 4.0],
        }
    )
    versions = prepare_versions(raw)
    june = versions.loc[versions["end_date"].eq(pd.Timestamp("2024-06-30"))].iloc[0]
    assert june["previous_q_profit_yoy"] == 30.0
    assert june["q_profit_yoy_acceleration"] == 20.0


def test_monthly_point_in_time_never_uses_future_revision():
    raw = pd.DataFrame(
        {
            "ts_code": ["A", "A", "A"],
            "ann_date": ["20240420", "20240515", "20240820"],
            "end_date": ["20240331", "20240331", "20240630"],
            "update_flag": [0, 1, 0],
            "q_profit_yoy": [10.0, 30.0, 50.0],
        }
    )
    versions = prepare_versions(raw)
    panel = monthly_point_in_time(
        versions, [pd.Timestamp("2024-04-30"), pd.Timestamp("2024-05-31")]
    )
    assert panel.loc[panel["signal_date"].eq(pd.Timestamp("2024-04-30")), "q_profit_yoy"].iloc[0] == 10.0
    assert panel.loc[panel["signal_date"].eq(pd.Timestamp("2024-05-31")), "q_profit_yoy"].iloc[0] == 30.0


def test_announcement_return_starts_at_close_before_disclosure():
    prices = pd.Series(
        [10.0, 20.0, 30.0, 40.0], index=pd.to_datetime(["2024-04-18", "2024-04-19", "2024-04-22", "2024-04-30"])
    )
    result = announcement_returns(
        prices,
        pd.Series(pd.to_datetime(["2024-04-20"])),
        pd.Series(pd.to_datetime(["2024-04-30"])),
    )
    assert np.isclose(result.iloc[0], 40 / 20 - 1)


def test_out_of_order_prior_disclosure_does_not_drop_current_report():
    raw = pd.DataFrame(
        {
            "ts_code": ["A", "A"],
            "ann_date": ["20240501", "20240420"],
            "end_date": ["20240331", "20240630"],
            "q_profit_yoy": [10.0, 20.0],
        }
    )
    versions = prepare_versions(raw)
    current = versions.loc[versions["end_date"].eq(pd.Timestamp("2024-06-30"))]
    assert len(current) == 1
    assert np.isnan(current.iloc[0]["previous_q_profit_yoy"])
