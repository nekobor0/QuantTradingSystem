from pathlib import Path

from scripts.data_lake.validate_macro_w1_package_contracts import validate_contracts


ROOT = Path(__file__).resolve().parents[2]


def test_five_package_contracts_cover_w1_exactly_once() -> None:
    result = validate_contracts(
        ROOT / "config" / "macro_w1_packages",
        ROOT / "config" / "macro_w1_confirmation_registry.json",
    )
    assert result["passed"] is True
    assert result["package_counts"] == {
        "rates_liquidity": 11,
        "pmi_state": 8,
        "prices": 5,
        "money_credit": 7,
        "growth_output": 3,
    }
