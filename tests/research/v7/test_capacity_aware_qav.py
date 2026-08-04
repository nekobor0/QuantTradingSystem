import numpy as np
import pandas as pd
import pytest

from quant_trading_system.research.v7.capacity_aware_qav import (
    add_capacity_aware_signals,
    constrained_rank_target,
    effective_days_last_60,
    monthly_signal_diagnostics,
    square_root_impact_cost,
)
from scripts.v7.run_capacity_aware_qav_v7 import (
    lane_a_marginal_diagnostic,
    stage_s_gates,
)


def test_effective_days_use_market_sessions_not_stock_observation_count() -> None:
    dates = pd.date_range("2024-01-01", periods=70, freq="B")
    daily = pd.DataFrame(
        {
            "ts_code": ["A"] * 70 + ["B"] * 35,
            "trade_date": [d.strftime("%Y%m%d") for d in dates]
            + [d.strftime("%Y%m%d") for d in dates[::2]],
        }
    )
    entries = pd.DataFrame(
        {
            "ts_code": ["A", "B"],
            "signal_date": [dates[-2], dates[-3]],
            "entry_date": [dates[-1], dates[-2]],
        }
    )
    result = effective_days_last_60(daily, entries).set_index("ts_code")
    assert result.at["A", "effective_days_60"] == 60
    assert result.at["B", "effective_days_60"] == 30


def test_effective_days_reject_duplicate_stock_day() -> None:
    daily = pd.DataFrame({"ts_code": ["A", "A"], "trade_date": ["20240101", "20240101"]})
    entries = pd.DataFrame(
        {"ts_code": ["A"], "signal_date": [pd.Timestamp("2023-12-31")], "entry_date": [pd.Timestamp("2024-01-01")]}
    )
    with pytest.raises(ValueError, match="duplicate"):
        effective_days_last_60(daily, entries)


def signal_frame() -> pd.DataFrame:
    date = pd.Timestamp("2024-01-31")
    return pd.DataFrame(
        {
            "ts_code": [f"S{i:03d}" for i in range(30)],
            "signal_date": [date] * 30,
            "baseline_value_z": np.linspace(-1, 2, 30),
            "baseline_quality_z": np.linspace(-2, 2, 30),
            "size": np.linspace(1e8, 5e9, 30),
            "adv20_cny": np.linspace(1e7, 1e8, 30),
            "l1_code": ["A", "B", "C"] * 10,
        }
    )


def test_capacity_signals_keep_raw_qav_direction_and_add_diagnostics() -> None:
    result = add_capacity_aware_signals(signal_frame())
    expected = result["baseline_value_z"] - (-result["baseline_quality_z"]).clip(lower=0)
    pd.testing.assert_series_equal(result["raw_signal"], expected, check_names=False)
    assert result["liquidity_neutral_signal"].notna().all()
    assert result["industry_within_signal"].notna().all()
    assert result["partial_signal"].notna().all()


def test_constrained_target_obeys_stock_and_positive_industry_active_caps() -> None:
    candidates = pd.DataFrame(
        {
            "ts_code": [f"S{i:03d}" for i in range(120)],
            "l1_code": ["A"] * 25 + ["B"] * 25 + ["C"] * 25 + ["D"] * 45,
            "raw_signal": np.arange(120, 0, -1),
        }
    )
    benchmark = pd.Series({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    target = constrained_rank_target(candidates, benchmark)
    industries = candidates.set_index("ts_code")["l1_code"].reindex(target.index)
    industry_weights = target.groupby(industries).sum()
    assert len(target) == 100
    assert target.sum() == pytest.approx(1)
    assert target.max() <= 0.02 + 1e-9
    assert (industry_weights - benchmark.reindex(industry_weights.index)).max() <= 0.05 + 1e-8


def test_rank_target_is_monotone_without_binding_industry_caps() -> None:
    candidates = pd.DataFrame(
        {
            "ts_code": [f"S{i:03d}" for i in range(100)],
            "l1_code": [f"I{i % 10}" for i in range(100)],
            "raw_signal": np.arange(100, 0, -1),
        }
    )
    benchmark = pd.Series({f"I{i}": 0.1 for i in range(10)})
    target = constrained_rank_target(candidates, benchmark)
    ordered = target.reindex(candidates["ts_code"])
    assert ordered.is_monotonic_decreasing
    assert ordered.iloc[0] > ordered.iloc[-1]


def test_square_root_impact_is_nonlinear_and_reports_participation() -> None:
    trades = pd.Series({"A": 0.01, "B": 0.02})
    adv = pd.Series({"A": 10_000_000.0, "B": 10_000_000.0})
    cost, participation = square_root_impact_cost(trades, adv)
    assert participation.to_dict() == pytest.approx({"A": 0.01, "B": 0.02})
    assert cost > 0
    assert cost < 0.5 * trades.abs().sum() * 0.001


def test_missing_adv_is_finite_cost_but_remains_visible_for_gate() -> None:
    trades = pd.Series({"A": 0.01})
    cost, participation = square_root_impact_cost(trades, pd.Series(dtype=float))
    assert np.isfinite(cost)
    assert participation.isna().all()


def test_signal_diagnostics_use_only_investable_complete_labels() -> None:
    signals = []
    labels = []
    for month in pd.to_datetime(["2024-01-31", "2024-02-29"]):
        for i in range(30):
            key = {"ts_code": f"S{i:03d}", "signal_date": month}
            signals.append(
                {
                    **key,
                    "investable_c7": i < 29,
                    "entry_tradable": True,
                    "partial_signal": float(i),
                    "raw_signal": float(i),
                    "adv20_cny": float(10_000_000 + i * 1_000_000),
                }
            )
            labels.append(
                {
                    **key,
                    "entry_tradable": True,
                    "exit_6m_tradable": True,
                    "forward_return_6m": float(i),
                }
            )
    monthly, summary = monthly_signal_diagnostics(
        pd.DataFrame(signals), pd.DataFrame(labels)
    )
    assert len(monthly) == 2
    assert summary["rows"] == 58
    assert summary["partial_rank_ic_6m"] == pytest.approx(1)


def test_stage_s_requires_all_four_preregistered_gates() -> None:
    passing = {
        "partial_rank_ic_6m": 0.031,
        "positive_ic_month_share": 0.56,
        "middle_liquidity_rank_ic_6m": 0.001,
        "highest_liquidity_rank_ic_6m": 0.001,
    }
    assert all(stage_s_gates(passing).values())
    for key in passing:
        failing = dict(passing)
        failing[key] = -0.001 if "rank_ic" in key else 0.55
        assert not all(stage_s_gates(failing).values())


def test_lane_a_marginal_diagnostic_is_explicitly_non_promotional() -> None:
    dates = pd.date_range("2024-01-31", periods=12, freq="ME")
    c7 = pd.DataFrame(
        {
            "signal_date": dates,
            "portfolio_net_return": np.linspace(-0.01, 0.02, 12),
            "benchmark_return": 0.0,
        }
    )
    lane_a = pd.DataFrame(
        {
            "index_code": "000852.SH",
            "signal_date": dates,
            "portfolio_net_return": np.linspace(-0.005, 0.01, 12),
            "benchmark_return": 0.0,
        }
    )
    result = lane_a_marginal_diagnostic(c7, lane_a)
    assert result["status"] == "POST_DECISION_DIAGNOSTIC_NOT_A_PROMOTION_GATE"
    assert "delta_ir" in result["benchmarks"]["000852.SH"]
