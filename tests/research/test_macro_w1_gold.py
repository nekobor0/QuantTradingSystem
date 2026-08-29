import json
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
    money = result["packages"]["money_credit"]
    assert money["status"] == "GOLD_BLOCKED_PARTIAL_5_OF_8"
    assert money["checks"]["five_of_eight_pre_candidate_exact"] is True
    assert money["checks"]["afre_semantic_policy_exact"] is True


def test_w1_gold_rejects_premature_afre_coverage(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    money = registry["packages"]["money_credit"]
    money["status"] = "GOLD_BLOCKED_PARTIAL_6_OF_8"
    money["covered_series"].append("CN.TSF.RMB_LOANS.FLOW")
    money["blocked_series"].remove("CN.TSF.RMB_LOANS.FLOW")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_registry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]
