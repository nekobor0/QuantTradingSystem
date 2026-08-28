from pathlib import Path

from scripts.data_lake.validate_macro_w1_full_entry import validate_full_entry


ROOT = Path(__file__).resolve().parents[2]


def test_w1_full_entry_has_pmi_prices_ready_with_other_packages_blocked():
    result = validate_full_entry(ROOT / "config" / "macro_w1_execution_manifest.json")
    assert result["passed"], result
    assert result["full_entry_ready"] is False
    assert result["decision"] == "MIXED_PACKAGE_READINESS"
    assert result["ready_packages"] == ["pmi_state", "prices"]
    assert result["blocked_packages"] == ["rates_liquidity", "money_credit", "growth_output"]


def test_promoted_packages_are_pending_until_real_full_audits_succeed():
    result = validate_full_entry(
        ROOT / "config" / "macro_w1_execution_manifest.json",
        ROOT / "artifacts" / "macro_r011" / "audits",
    )
    assert result["passed"], result
    assert result["execution_pending_packages"] == ["pmi_state", "prices"]
    assert result["full_history_complete_packages"] == []
