import numpy as np
import pandas as pd
import pytest

from quant_trading_system.research.v6.incremental_evaluation import (
    compare_portfolios,
    downside_beta,
    weighted_holding_overlap,
)


def monthly(returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "index_code": ["I"] * len(returns),
            "signal_date": pd.date_range("2024-01-31", periods=len(returns), freq="ME"),
            "portfolio_net_return": returns,
            "benchmark_return": [-0.02, 0.01, -0.01, 0.02],
            "turnover": [0.1] * len(returns),
        }
    )


def test_downside_beta_and_incremental_delta():
    baseline = monthly([-0.02, 0.01, -0.01, 0.02])
    candidate = monthly([-0.01, 0.01, -0.005, 0.02])
    assert downside_beta(
        baseline["portfolio_net_return"], baseline["benchmark_return"]
    ) == pytest.approx(1.0)
    report = compare_portfolios(baseline, candidate)
    assert report["benchmarks"]["I"]["candidate_downside_beta"] == pytest.approx(0.5)
    assert report["benchmarks"]["I"]["delta"]["downside_beta"] == pytest.approx(-0.5)


def test_weighted_holding_overlap_and_month_mismatch_fail_closed():
    baseline_holdings = pd.DataFrame(
        {
            "index_code": ["I", "I"],
            "signal_date": pd.to_datetime(["2024-01-31", "2024-01-31"]),
            "ts_code": ["A", "B"],
            "weight": [0.6, 0.4],
        }
    )
    candidate_holdings = baseline_holdings.assign(weight=[0.3, 0.7])
    assert np.isclose(
        weighted_holding_overlap(baseline_holdings, candidate_holdings), 0.7
    )
    with pytest.raises(ValueError, match="months"):
        compare_portfolios(monthly([0.0] * 4), monthly([0.0] * 4).iloc[:-1])

