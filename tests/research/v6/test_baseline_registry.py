from copy import deepcopy
from pathlib import Path

import pytest

from quant_trading_system.research.v6.baseline_registry import (
    assert_registry_matches,
    build_registry_snapshot,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_frozen_v5_registry_recomputes_all_three_baselines():
    snapshot = build_registry_snapshot(
        PROJECT_ROOT,
        PROJECT_ROOT / "development/16-alpha-factor-phase1/GOAL_V6.md",
        PROJECT_ROOT
        / "development/16-alpha-factor-phase1/PORTFOLIO_EVALUATOR_V5_SPEC.md",
    )
    assert set(snapshot["baselines"]) == {
        "equal_style_p0",
        "historical_icir",
        "rolling_regression_24m",
    }
    assert snapshot["baselines"]["rolling_regression_24m"]["monthly"]["rows"] == 190
    assert (
        snapshot["baselines"]["rolling_regression_24m"]["fixed_validation"][
            "000300.SH"
        ]["annual_excess_return_difference"]
        > 0.03
    )


def test_registry_drift_is_fail_closed():
    expected = {"version": 6, "file": {"sha256": "original"}}
    changed = deepcopy(expected)
    changed["file"]["sha256"] = "mutated"
    with pytest.raises(ValueError, match="drift"):
        assert_registry_matches(expected, changed)

