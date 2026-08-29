from pathlib import Path

from scripts.data_lake.validate_macro_w1_gold import validate_registry


ROOT = Path(__file__).resolve().parents[2]


def test_w1_gold_registry_has_evidence_backed_ready_and_blocked_packages():
    result = validate_registry(ROOT / "config" / "macro_w1_gold_registry.json")
    assert result["passed"], result
    assert result["ready_packages"] == ["growth_output", "pmi_state", "prices"]
    assert result["blocked_packages"] == ["money_credit", "rates_liquidity"]
    rates = result["packages"]["rates_liquidity"]
    assert rates["status"] == "GOLD_BLOCKED_PARTIAL_9_OF_11"
    assert rates["gold_ready_count"] == 9
    assert rates["gold_required_count"] == 11
    assert rates["package_ready"] is False
