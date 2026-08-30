import copy
import json
from pathlib import Path

import pytest

from scripts.data_lake.validate_macro_w1_money_credit_full_contract import (
    validate_money_credit_full_contract,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "config" / "macro_w1_packages" / "money_credit.json"
MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"


def _documents(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    package_path = tmp_path / "money_credit.json"
    manifest_path = tmp_path / "manifest.json"
    return package, manifest, package_path, manifest_path


def _write(package: dict, manifest: dict, package_path: Path, manifest_path: Path) -> None:
    package_path.write_text(json.dumps(package), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _manifest_contract(manifest: dict) -> dict:
    money = next(item for item in manifest["packages"] if item["package_id"] == "money_credit")
    return money["pending_full_history_contract"]


def test_frozen_money_credit_full_contract_passes() -> None:
    result = validate_money_credit_full_contract(PACKAGE, MANIFEST)
    assert result["passed"], result
    assert result["calendar_rows_total"] == 1165
    assert list(result["series_windows"]) == [
        "CN.MONEY.M1.BALANCE",
        "CN.MONEY.M2.BALANCE",
        "CN.TSF.FLOW",
        "CN.TSF.STOCK",
        "CN.TSF.GOV_BOND.FLOW",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "bad_start",
        "bad_end",
        "bad_rows",
        "bad_unit",
        "bad_basis",
        "drop_series",
        "wrong_order",
        "wrong_source",
        "allow_full",
        "allow_formal",
        "mark_written",
        "research_ready",
        "allow_cumulative_diff",
        "allow_balance_diff",
        "allow_interpolation",
        "allow_zero_fill",
        "allow_forward_fill",
        "drop_methodology_break",
        "package_formal_complete",
        "afre_formal_unwritten",
        "manifest_drift",
    ],
)
def test_frozen_money_credit_full_contract_fails_closed(tmp_path: Path, mutation: str) -> None:
    package, manifest, package_path, manifest_path = _documents(tmp_path)
    contract = package["pending_full_history_contract"]
    manifest_contract = _manifest_contract(manifest)
    if mutation == "bad_start":
        contract["series_windows"]["CN.MONEY.M1.BALANCE"]["start"] = "2000-01"
    elif mutation == "bad_end":
        contract["series_windows"]["CN.TSF.FLOW"]["end"] = "2026-08"
    elif mutation == "bad_rows":
        contract["series_windows"]["CN.TSF.STOCK"]["calendar_rows"] = 114
    elif mutation == "bad_unit":
        contract["series_windows"]["CN.TSF.STOCK"]["unit"] = "100m_cny"
    elif mutation == "bad_basis":
        contract["series_windows"]["CN.TSF.FLOW"]["measure_basis"] = "stock"
    elif mutation == "drop_series":
        contract["series_windows"].pop("CN.TSF.GOV_BOND.FLOW")
    elif mutation == "wrong_order":
        contract["series_order"] = list(reversed(contract["series_order"]))
    elif mutation == "wrong_source":
        contract["source_whitelist"] = ["THIRD_PARTY"]
    elif mutation == "allow_full":
        contract["full_history_allowed"] = True
    elif mutation == "allow_formal":
        contract["formal_execution_allowed"] = True
    elif mutation == "mark_written":
        contract["formal_curated_written"] = True
    elif mutation == "research_ready":
        contract["research_ready"] = True
    elif mutation == "allow_cumulative_diff":
        contract["candidate_rules"]["cumulative_differencing_allowed"] = True
    elif mutation == "allow_balance_diff":
        contract["candidate_rules"]["balance_differencing_allowed"] = True
    elif mutation == "allow_interpolation":
        contract["candidate_rules"]["interpolation_allowed"] = True
    elif mutation == "allow_zero_fill":
        contract["candidate_rules"]["zero_fill_allowed"] = True
    elif mutation == "allow_forward_fill":
        contract["candidate_rules"]["forward_fill_allowed"] = True
    elif mutation == "drop_methodology_break":
        contract["required_methodology_breaks"].pop()
    elif mutation == "package_formal_complete":
        package["formal_execution_state"] = "COMPLETE"
    elif mutation == "afre_formal_unwritten":
        package["afre_full_history_gate"]["formal_curated_written"] = False
    else:
        manifest_contract["calendar_rows_total"] = 1164
    if mutation != "manifest_drift":
        _manifest_contract(manifest).clear()
        _manifest_contract(manifest).update(copy.deepcopy(contract))
    _write(package, manifest, package_path, manifest_path)
    result = validate_money_credit_full_contract(package_path, manifest_path)
    assert not result["passed"], mutation
