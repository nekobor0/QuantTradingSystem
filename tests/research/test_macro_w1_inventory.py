from pathlib import Path

from scripts.data_lake.validate_macro_w1_inventory import validate_inventory


ROOT = Path(__file__).resolve().parents[2]


def test_w1_inventory_matches_actual_34_series_state() -> None:
    result = validate_inventory(ROOT / "config" / "macro_w1_confirmation_registry.json")
    assert result["passed"] is True
    assert result["package_counts"] == {
        "rates_liquidity": 11,
        "pmi_state": 8,
        "prices": 5,
        "money_credit": 7,
        "growth_output": 3,
    }
