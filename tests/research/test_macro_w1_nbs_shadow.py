from pathlib import Path

import pytest

from scripts.data_lake.run_macro_w1_nbs_shadow import run


ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "artifacts" / "macro_r011" / "gold_fixtures"
requires_gold = pytest.mark.skipif(not (GOLD / "w1_pmi_state" / "2026-06" / "expected.json").is_file(), reason="ignored local Gold absent")


@requires_gold
@pytest.mark.parametrize("package_id", ["pmi_state", "prices", "growth_output"])
def test_nbs_package_reparse_matches_two_official_gold_periods(package_id: str):
    output_root = ROOT / "artifacts" / "macro_r011" / "test_runs" / package_id
    result = run(package_id, output_root)
    assert result["sol_gate_passed"], result
    assert result["audit"]["research_ready"] is False
