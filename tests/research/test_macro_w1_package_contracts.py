import json
from pathlib import Path
import shutil
import pytest

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
        "money_credit": 8,
        "growth_output": 3,
    }


def test_money_contract_rejects_afre_alias_or_missing_decision(tmp_path: Path) -> None:
    contract_root = tmp_path / "contracts"
    shutil.copytree(ROOT / "config" / "macro_w1_packages", contract_root)
    path = contract_root / "money_credit.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["accepted_decisions"].remove("W1_D10")
    contract["series"][-1]["series_id"] = "CN.LOANS.RMB.FLOW"
    path.write_text(json.dumps(contract), encoding="utf-8")
    result = validate_contracts(contract_root, ROOT / "config" / "macro_w1_confirmation_registry.json")
    assert not result["passed"]
    assert {"all_decisions_frozen", "series_union_exact"}.issubset(result["failures"])


@pytest.mark.parametrize("mutation", ["required", "cumulative", "balance", "alias"])
def test_money_contract_rejects_reactivating_or_deriving_retired_raw_series(tmp_path: Path, mutation: str) -> None:
    contract_root = tmp_path / "contracts"
    shutil.copytree(ROOT / "config" / "macro_w1_packages", contract_root)
    path = contract_root / "money_credit.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "required":
        retired = next(item for item in contract["series"] if item["series_id"] == "CN.LOANS.RMB.FLOW")
        retired["required"] = True
    elif mutation == "cumulative":
        contract["canonical_scope_policy"]["cumulative_differencing_allowed"] = True
    elif mutation == "balance":
        contract["canonical_scope_policy"]["balance_differencing_allowed"] = True
    else:
        contract["canonical_scope_policy"]["aliases_forbidden"] = {}
    path.write_text(json.dumps(contract), encoding="utf-8")
    result = validate_contracts(contract_root, ROOT / "config" / "macro_w1_confirmation_registry.json")
    assert not result["passed"]
    assert "money_active_required_scope_exact" in result["failures"]
