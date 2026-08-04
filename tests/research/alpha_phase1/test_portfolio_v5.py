import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    STYLE_COMPONENTS,
    build_adaptive_composite_scores,
    construct_industry_rotation_target,
    enforce_execution_and_turnover,
    performance_metrics,
)


def test_rotation_preserves_industry_and_caps_stock_and_size():
    universe = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D"],
            "l1_code": ["I1", "I1", "I2", "I2"],
            "style_baseline_equal_weight": [-1.0, 1.0, -1.0, 1.0],
            "size_z": [-1.0, 1.0, -1.0, 1.0],
            "eligible_entry": [True] * 4,
        }
    )
    benchmark = pd.Series({"A": 0.5, "C": 0.5})
    target = construct_industry_rotation_target(
        universe, benchmark, active_fraction=0.2, receiver_count=1, stock_cap=0.8
    )
    industries = universe.set_index("ts_code")["l1_code"]
    assert np.isclose(target.groupby(industries).sum()["I1"], 0.5)
    assert np.isclose(target.groupby(industries).sum()["I2"], 0.5)
    assert target.max() <= 0.8 + 1e-12
    base_size = float(
        (benchmark * universe.set_index("ts_code")["size_z"].reindex(benchmark.index)).sum()
    )
    target_size = float((target * universe.set_index("ts_code")["size_z"].reindex(target.index)).sum())
    assert abs(target_size - base_size) <= 0.25 + 1e-12


def test_execution_keeps_an_untradable_holding_and_caps_turnover():
    target = pd.Series({"A": 0.0, "B": 1.0})
    pretrade = pd.Series({"A": 1.0})
    actual, turnover = enforce_execution_and_turnover(
        target, pretrade, pd.Series({"A": False, "B": True}), turnover_cap=1.0
    )
    assert np.isclose(actual["A"], 1.0)
    assert turnover == 0.0


def test_performance_metrics_uses_ex_post_active_returns():
    monthly = pd.DataFrame(
        {
            "portfolio_net_return": [0.02, 0.01, -0.01],
            "benchmark_return": [0.01, 0.0, -0.02],
            "turnover": [0.2, 0.1, 0.1],
        }
    )
    metrics = performance_metrics(monthly)
    assert metrics["months"] == 3
    assert np.isclose(metrics["tracking_error"], 0.0)
    assert metrics["monthly_excess_win_rate"] == 1.0


def test_adaptive_scores_use_only_returns_that_have_exited():
    rows = []
    dates = pd.date_range("2020-01-31", periods=26, freq="ME")
    for month_number, signal_date in enumerate(dates):
        for stock_number in range(8):
            row = {
                "ts_code": f"S{stock_number}",
                "signal_date": signal_date,
                "exit_date": signal_date + pd.offsets.MonthEnd(2),
                "mark_return_1m": float(stock_number),
            }
            row.update(
                {
                    component: (
                        float(stock_number)
                        if component == STYLE_COMPONENTS[0]
                        else -float(stock_number)
                    )
                    for component in STYLE_COMPONENTS
                }
            )
            rows.append(row)
    panel = pd.DataFrame(rows)
    scored, audit = build_adaptive_composite_scores(panel, minimum_history_months=24)
    final_audit = audit[audit["signal_date"].eq(dates[-1])]
    assert set(final_audit["history_months"]) == {24}
    assert set(final_audit["latest_used_signal_date"]) == {dates[-3]}
    weight_columns = [f"weight_{component}" for component in STYLE_COMPONENTS]
    assert (final_audit[weight_columns] >= 0).all().all()
    assert np.allclose(final_audit[weight_columns].sum(axis=1), 1.0)
    assert scored["style_baseline_historical_icir"].notna().all()
