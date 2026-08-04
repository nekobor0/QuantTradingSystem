import numpy as np
import pandas as pd

from scripts.alpha_phase1.audit_benchmark_risk_v5 import (
    audit_benchmark,
    cross_sectional_zscore,
)


def test_cross_sectional_zscore_has_zero_mean_and_unit_std():
    result = cross_sectional_zscore(pd.Series([1.0, 2.0, 3.0]))
    assert np.isclose(result.mean(), 0.0)
    assert np.isclose(result.std(ddof=0), 1.0)


def test_benchmark_audit_reports_missing_return_weight():
    date = pd.Timestamp("2024-01-31")
    weights = pd.DataFrame(
        {
            "trade_date": ["20240131", "20240131"],
            "con_code": ["A", "B"],
            "weight": [60.0, 40.0],
        }
    )
    panel = pd.DataFrame(
        {
            "signal_date": [date, date],
            "ts_code": ["A", "B"],
            "forward_return": [0.10, np.nan],
            "l1_code": ["I1", "I2"],
            "size": [1.0, 2.0],
            **{column: [0.0, 1.0] for column in [
                "size_z", "beta", "momentum", "liquidity", "residual_volatility",
                "value_composite", "investment", "quality_composite", "leverage",
            ]},
        }
    )
    weights = pd.concat(
        [weights, weights.assign(trade_date="20240229")], ignore_index=True
    )
    panel = pd.concat(
        [panel, panel.assign(signal_date=pd.Timestamp("2024-02-29"))], ignore_index=True
    )
    daily = pd.DataFrame(
        {
            "trade_date": ["20240201", "20240301"],
            "open": [100.0, 105.0],
        }
    )
    report, monthly, industries = audit_benchmark("TEST", weights, panel, daily)
    assert np.isclose(monthly.loc[0, "constituent_label_coverage_weight"], 0.6)
    assert np.isclose(monthly.loc[0, "benchmark_return"], 0.05)
    assert report["months_constituent_label_coverage_below_99pct"] == 2
    assert all(
        np.isclose(value, 1.0)
        for value in industries.groupby("signal_date")["weight"].sum()
    )
