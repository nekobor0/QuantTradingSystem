from pathlib import Path
import json
import shutil

from scripts.data_lake.validate_macro_w1_inventory import validate_inventory


ROOT = Path(__file__).resolve().parents[2]


def test_w1_inventory_matches_actual_44_series_state() -> None:
    result = validate_inventory(ROOT / "config" / "macro_w1_confirmation_registry.json")
    assert result["passed"] is True
    assert result["package_counts"] == {
        "rates_liquidity": 11,
        "pmi_state": 8,
        "prices": 5,
        "money_credit": 8,
        "growth_output": 3,
        "global_financial_conditions": 9,
    }
    assert result["state_counts"]["FULL_HISTORY_EVIDENCE_ACCEPTED_PIT_C_FORMAL_NOT_AUTHORIZED"] == 7
    assert result["state_counts"]["OFFICIAL_PRODUCT_CONFIRMED_ENTITLEMENT_BLOCKED"] == 1


def test_w1_inventory_rejects_global_gold_state_tamper(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    shutil.copy2(ROOT / "config" / "macro_w1_confirmation_registry.json", path)
    registry = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in registry["series"] if item["canonical_id"] == "US.EFFR")
    row["state"] = "CONTRACT_ONLY"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_inventory(path)
    assert not result["passed"]
    assert "global_gold_7_of_9_exact" in result["failures"]
