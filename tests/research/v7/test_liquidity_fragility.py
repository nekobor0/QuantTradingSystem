import numpy as np
import pandas as pd
import pytest

from quant_trading_system.research.v7.liquidity_fragility import (
    cross_sectional_fragility,
    rolling_liquidity_fragility,
)
from scripts.v7.run_liquidity_fragility_v7 import (
    all_benchmark_gates_pass,
    stage_s_gates,
)


def test_future_append_does_not_change_historical_fragility() -> None:
    dates = pd.date_range("2022-01-03", periods=320, freq="B")
    returns = pd.Series(np.sin(np.arange(320)) / 100, index=dates)
    amount = pd.Series(np.linspace(1e7, 2e7, 320), index=dates)
    market = pd.Series(np.cos(np.arange(320)) / 100, index=dates)
    original = rolling_liquidity_fragility(returns, amount, market)
    future_date = dates[-1] + pd.offsets.BDay()
    extended = rolling_liquidity_fragility(
        pd.concat([returns, pd.Series([9.0], index=[future_date])]),
        pd.concat([amount, pd.Series([1.0], index=[future_date])]),
        pd.concat([market, pd.Series([-9.0], index=[future_date])]),
    )
    pd.testing.assert_frame_equal(
        original, extended.loc[original.index], check_freq=False
    )


def test_amount_contraction_increases_when_recent_amount_falls() -> None:
    dates = pd.date_range("2022-01-03", periods=320, freq="B")
    returns = pd.Series(np.tile([0.01, -0.01], 160), index=dates)
    market = pd.Series(np.tile([-0.01, 0.01], 160), index=dates)
    stable = pd.Series(1e8, index=dates)
    contracted = stable.copy()
    contracted.iloc[-20:] = 1e7
    baseline = rolling_liquidity_fragility(returns, stable, market)
    stressed = rolling_liquidity_fragility(returns, contracted, market)
    assert stressed["amount_contraction"].iloc[-1] > baseline["amount_contraction"].iloc[-1]


def test_cross_sectional_score_points_toward_low_fragility() -> None:
    rows = []
    date = pd.Timestamp("2024-01-31")
    for index in range(30):
        rows.append(
            {
                "ts_code": f"S{index:03d}",
                "signal_date": date,
                "l1_code": f"I{index % 3}",
                "size": float(100 + index),
                "beta": float(index) / 100,
                "eligible_signal": True,
                "amihud_abnormal": float(index),
                "amount_contraction": float(index),
                "down_vol_amplification": float(index),
            }
        )
    result = cross_sectional_fragility(pd.DataFrame(rows))
    assert result.loc[0, "defensive_score"] > result.loc[29, "defensive_score"]
    assert result["partial_signal"].notna().all()


def test_cross_sectional_signal_requires_all_components() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": [pd.Timestamp("2024-01-31")],
            "l1_code": ["I"],
            "size": [1.0],
            "beta": [1.0],
            "eligible_signal": [True],
            "amihud_abnormal": [1.0],
        }
    )
    with pytest.raises(ValueError, match="missing B7"):
        cross_sectional_fragility(frame)


def test_stage_s_rejects_beta_repackaging() -> None:
    summary = {
        "partial_rank_ic_1m_down_months": 0.01,
        "positive_ic_month_share": 0.60,
        "absolute_median_beta_correlation": 0.60,
    }
    assert not stage_s_gates(summary)["passes_all"]


def test_both_benchmarks_must_pass() -> None:
    results = {
        "000300.SH": {"gates": {"passes_all": True}},
        "000852.SH": {"gates": {"passes_all": False}},
    }
    assert not all_benchmark_gates_pass(results)
