from pathlib import Path

from scripts.data_lake.validate_macro_w1_gate import validate


ROOT = Path(__file__).resolve().parents[2]


def test_w1_confirmation_registry_is_closed_and_exactly_34_series():
    result = validate(
        ROOT / "config" / "macro_w1_confirmation_registry.json",
        ROOT / "development" / "18-macro-data-layer" / "R011_macro_data_prioritization" / "02_china_macro_data_universe_v0.1.yaml",
    )
    assert result["passed"], result["failures"]
    assert result["package_counts"] == {
        "rates_liquidity": 11,
        "pmi_state": 8,
        "prices": 5,
        "money_credit": 7,
        "growth_output": 3,
    }
