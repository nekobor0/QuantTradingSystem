import json
from pathlib import Path

from scripts.data_lake.validate_macro_w1_gate import validate


ROOT = Path(__file__).resolve().parents[2]


def test_w1_confirmation_registry_records_all_decisions_and_exactly_35_series():
    result = validate(
        ROOT / "config" / "macro_w1_confirmation_registry.json",
        ROOT / "development" / "18-macro-data-layer" / "R011_macro_data_prioritization" / "02_china_macro_data_universe_v0.1.yaml",
    )
    assert result["passed"], result["failures"]
    assert result["package_counts"] == {
        "rates_liquidity": 11,
        "pmi_state": 8,
        "prices": 5,
        "money_credit": 8,
        "growth_output": 3,
    }


def test_w1_confirmation_registry_rejects_missing_afre_decision(tmp_path: Path):
    registry = json.loads((ROOT / "config" / "macro_w1_confirmation_registry.json").read_text(encoding="utf-8"))
    registry["confirmed_decision_ids"].remove("W1_D10")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate(
        path,
        ROOT / "development" / "18-macro-data-layer" / "R011_macro_data_prioritization" / "02_china_macro_data_universe_v0.1.yaml",
    )
    assert not result["passed"]
    assert "all_decisions_confirmed" in result["failures"]
