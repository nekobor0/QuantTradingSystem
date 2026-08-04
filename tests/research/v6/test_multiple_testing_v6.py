import pandas as pd

from scripts.v6.update_multiple_testing_v6 import (
    block_bootstrap_mean,
    downside_improvement_series,
    hac_mean_test,
)


def test_downside_improvement_and_statistics_are_deterministic() -> None:
    keys = {
        "index_code": ["X"] * 6,
        "signal_date": pd.date_range("2023-07-31", periods=6, freq="ME"),
        "benchmark_return": [-0.02, 0.01, -0.03, 0.02, -0.01, 0.01],
    }
    baseline = pd.DataFrame({**keys, "portfolio_net_return": [-0.02, 0, -0.03, 0, -0.01, 0]})
    candidate = pd.DataFrame({**keys, "portfolio_net_return": [-0.01, 0, -0.02, 0, 0.0, 0]})
    improvement = downside_improvement_series(baseline, candidate)
    assert improvement.tolist() == pytest.approx([0.01, 0.01, 0.01])
    assert hac_mean_test(improvement)["estimate"] == pytest.approx(0.01)
    first = block_bootstrap_mean(improvement, samples=20)
    second = block_bootstrap_mean(improvement, samples=20)
    assert first == second


import pytest
