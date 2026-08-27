from pathlib import Path

from scripts.data_lake.validate_macro_w1_gold import validate_registry


ROOT = Path(__file__).resolve().parents[2]


def test_w1_gold_registry_has_evidence_backed_ready_and_blocked_packages():
    result = validate_registry(ROOT / "config" / "macro_w1_gold_registry.json")
    assert result["passed"], result
    assert result["ready_packages"] == ["growth_output", "pmi_state", "prices"]
    assert result["blocked_packages"] == ["money_credit", "rates_liquidity"]
