from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.long_only_evaluation import (
    decile_analysis,
    neutralize,
    quality_summary,
    turnover_summary,
)


def _frame() -> pd.DataFrame:
    rows = []
    for month in ("2024-01-31", "2024-02-29"):
        for number in range(200):
            rows.append(
                {
                    "ts_code": f"{number:06d}.SZ",
                    "signal_date": pd.Timestamp(month),
                    "factor": float(number),
                    "forward_return": number / 10_000,
                    "eligible_evaluation": True,
                    "eligible_quality": True,
                    "circ_mv": 100.0,
                    "is_st": number == 0,
                    "log_circ_mv": number / 200,
                    "volatility_60": (number % 13) / 13,
                    "log_turnover": (number % 17) / 17,
                    "momentum_12_1": (number % 19) / 19,
                    "l1_code": f"I{number % 4}",
                }
            )
    return pd.DataFrame(rows)


def test_decile_analysis_uses_highest_group_as_d1_and_computes_turnover() -> None:
    frame = _frame()
    summary, holdings = decile_analysis(frame, "factor")

    assert summary["increasing_adjacent_pairs"] == 9
    assert summary["d1_excess"]["mean"] > 0
    assert summary["d1_minus_d10"] > 0
    assert turnover_summary(holdings)["monthly_one_way_mean"] == 0.0


def test_neutralization_removes_declared_numeric_and_industry_exposures() -> None:
    frame = _frame()
    frame["factor"] = (
        3 * frame["log_circ_mv"]
        + 2 * frame["volatility_60"]
        + frame["log_turnover"]
        + frame["momentum_12_1"]
        + frame["l1_code"].str[1:].astype(float)
        + np.sin(np.arange(len(frame))) * 0.01
    )

    residual = neutralize(frame, "factor")

    assert residual.notna().all()
    for column in ("log_circ_mv", "volatility_60", "log_turnover", "momentum_12_1"):
        assert abs(residual.corr(frame[column])) < 0.01
    assert all(abs(residual.groupby(frame["l1_code"]).mean()) < 1e-10)


def test_neutralization_accepts_factor_that_is_also_a_control() -> None:
    frame = _frame()

    residual = neutralize(frame, "momentum_12_1")

    assert residual.notna().all()


def test_quality_is_measured_on_tradable_pit_pool_and_cap_weighted() -> None:
    frame = _frame()
    frame.loc[0, "factor"] = np.nan
    result = quality_summary(frame, "factor")

    assert result["eligible_rows"] == 400
    assert np.isclose(result["missing_rate"], 1 / 400)
    assert np.isclose(result["float_mv_coverage"], 399 / 400)
    assert np.isclose(result["st_row_share"], 2 / 400)
