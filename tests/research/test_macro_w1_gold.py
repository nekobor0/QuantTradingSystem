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
    assert money["status"] == "GOLD_BLOCKED_PARTIAL_6_OF_8"
    assert money["gold_ready_count"] == 6
    assert money["gold_required_count"] == 8
    assert money["gold_missing"] == ["CN.LOANS.CORP.MEDIUM_LONG.FLOW", "CN.LOANS.RMB.FLOW"]
    assert money["checks"]["legacy_five_of_eight_partition_exact"] is True
    assert money["checks"]["candidate_evidence_valid"] is True
    assert money["checks"]["six_of_eight_effective_coverage_exact"] is True
    assert money["checks"]["afre_semantic_policy_exact"] is True
    assert money["checks"]["afre_series_gold_state_exact"] is True


def test_w1_gold_rejects_candidate_frozen_sha_tamper(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    money = registry["packages"]["money_credit"]
    money["candidate_evidence"]["frozen_sha256"]["expected.json"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_registry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]
