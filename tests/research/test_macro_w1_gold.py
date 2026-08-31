import json
from pathlib import Path

from scripts.data_lake.validate_macro_w1_gold import validate_registry


ROOT = Path(__file__).resolve().parents[2]


def test_w1_gold_registry_has_evidence_backed_ready_and_blocked_packages():
    result = validate_registry(ROOT / "config" / "macro_w1_gold_registry.json")
    assert result["passed"], result
    assert result["ready_packages"] == ["growth_output", "money_credit", "pmi_state", "prices", "rates_liquidity"]
    assert result["blocked_packages"] == ["global_financial_conditions"]
    rates = result["packages"]["rates_liquidity"]
    assert rates["status"] == "GOLD_READY_11_OF_11_FULL_HISTORY_BLOCKED_CFETS"
    assert rates["gold_ready_count"] == 11
    assert rates["gold_required_count"] == 11
    assert rates["gold_missing"] == []
    assert rates["full_history_blocked_series"] == ["CN.REPO.DR007", "CN.REPO.R007"]
    assert rates["package_ready"] is True
    money = result["packages"]["money_credit"]
    assert money["status"] == "GOLD_READY_ACTIVE_6_OF_6"
    assert money["gold_ready_count"] == 6
    assert money["gold_required_count"] == 6
    assert money["gold_missing"] == []
    assert money["retired_not_required"] == ["CN.LOANS.CORP.MEDIUM_LONG.FLOW", "CN.LOANS.RMB.FLOW"]
    assert money["checks"]["legacy_fixture_partition_exact"] is True
    assert money["checks"]["candidate_evidence_valid"] is True
    assert money["checks"]["active_six_of_six_effective_coverage_exact"] is True
    assert money["checks"]["canonical_scope_policy_exact"] is True
    assert money["checks"]["afre_semantic_policy_exact"] is True
    assert money["checks"]["afre_series_gold_state_exact"] is True
    global_package = result["packages"]["global_financial_conditions"]
    assert global_package["status"] == "GOLD_BLOCKED_PARTIAL_7_OF_9"
    assert global_package["gold_ready_count"] == 7
    assert global_package["gold_required_count"] == 9
    assert global_package["gold_missing"] == ["USD.CNY", "USD.CNH"]
    assert global_package["package_ready"] is False
    assert global_package["checks"]["fx_blocked_evidence_valid"] is True
    assert global_package["checks"]["fx_frozen_evidence_exact"] is True


def test_w1_gold_rejects_global_fx_blocked_evidence_sha_tamper(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    registry["packages"]["global_financial_conditions"]["fx_blocked_evidence"]["frozen_sha256"]["candidate_audit"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_registry(path)
    assert not result["passed"]
    assert "global_financial_conditions" in result["invalid_packages"]


def test_w1_gold_rejects_global_candidate_frozen_sha_tamper(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    registry["packages"]["global_financial_conditions"]["frozen_sha256"]["expected.json"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_registry(path)
    assert not result["passed"]
    assert "global_financial_conditions" in result["invalid_packages"]


def test_w1_gold_rejects_candidate_frozen_sha_tamper(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    money = registry["packages"]["money_credit"]
    money["candidate_evidence"]["frozen_sha256"]["expected.json"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_registry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]


def test_w1_gold_rejects_retired_series_restored_to_required_scope(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    registry["packages"]["money_credit"]["effective_gold_coverage"]["required_count"] = 8
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_registry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]
