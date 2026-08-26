from pathlib import Path

from scripts.data_lake.validate_macro_w1_rates_contract import validate_contract


ROOT = Path(__file__).resolve().parents[2]


def test_w1_rates_contract_freezes_confirmed_decisions_and_mlf_break():
    result = validate_contract(ROOT / "config" / "macro_w1_rates_contract.json")
    assert result["passed"], result["failures"]

