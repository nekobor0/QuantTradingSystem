from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.classified_evaluation import (
    newey_west_summary,
    short_top_group_series,
    tail_analysis,
)
from scripts.alpha_phase1.evaluate_short_horizon_v3 import assign_industry


def test_tail_analysis_uses_highest_five_percent_without_requiring_monotonicity() -> None:
    rows = []
    for month in ("2024-01-31", "2024-02-29"):
        for number in range(400):
            rows.append(
                {
                    "ts_code": f"{number:06d}.SZ",
                    "signal_date": pd.Timestamp(month),
                    "factor": float(number),
                    "forward_return": 0.02 if number >= 380 else 0.0,
                    "eligible_evaluation": True,
                    "l1_code": f"I{number % 10}",
                }
            )
    result, holdings = tail_analysis(pd.DataFrame(rows), "factor")

    assert np.isclose(result["excess"]["mean"], 0.019)
    assert result["excess"]["positive_ratio"] == 1.0
    assert result["average_max_industry_weight"] == 0.1
    assert len(next(iter(holdings.values()))) == 20


def test_tail_analysis_fails_closed_when_domain_has_fewer_than_twenty_names() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": [f"{number:06d}.SZ" for number in range(19)],
            "signal_date": pd.Timestamp("2024-01-31"),
            "factor": range(19),
            "forward_return": 0.01,
            "eligible_evaluation": True,
            "l1_code": "I1",
        }
    )

    result, holdings = tail_analysis(frame, "factor")

    assert result["excess"]["months"] == 0
    assert holdings == {}


def test_short_top_group_deducts_fixed_two_way_cost() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": [f"{number:06d}.SZ" for number in range(200)],
            "signal_date": pd.Timestamp("2024-01-31"),
            "factor": range(200),
            "forward_return_5": [0.0] * 180 + [0.02] * 20,
            "eligible_evaluation": True,
        }
    )
    values, holdings = short_top_group_series(frame, "factor", 5)

    assert np.isclose(values.iloc[0], 0.0175)
    assert len(next(iter(holdings.values()))) == 20


def test_newey_west_summary_reports_hac_t_statistic() -> None:
    result = newey_west_summary(pd.Series([0.01, 0.02, 0.01, 0.03, 0.02]), lags=1)

    assert result["observations"] == 5
    assert np.isclose(result["mean"], 0.018)
    assert result["t_stat_hac"] is not None


def test_daily_industry_assignment_respects_in_and_out_dates() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "signal_date": pd.to_datetime(["2024-01-31", "2024-02-29"]),
        }
    )
    members = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "l1_code": ["OLD", "NEW"],
            "in_date": ["20200101", "20240215"],
            "out_date": ["20240215", ""],
        }
    )

    result = assign_industry(frame, members)

    assert result.tolist() == ["OLD", "NEW"]
