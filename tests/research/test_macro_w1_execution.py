from datetime import date
import json
from pathlib import Path

from quant_trading_system.research.macro_data.w1_execution import build_audit, expected_periods, validate_audit
from scripts.data_lake.validate_macro_w1_full_entry import validate_full_entry


ROOT = Path(__file__).resolve().parents[2]


def test_expected_periods_handle_month_quarter_and_joint_january_february():
    assert expected_periods(date(2026, 1, 1), date(2026, 3, 31), "monthly") == ["2026-01", "2026-02", "2026-03"]
    assert expected_periods(date(2026, 1, 1), date(2026, 7, 1), "quarterly") == ["2026-Q1", "2026-Q2", "2026-Q3"]
    assert expected_periods(date(2026, 1, 1), date(2026, 3, 31), "monthly_with_jan_feb_joint") == ["2026-01_02", "2026-03"]


def test_audit_blocker_semantics_are_machine_checked():
    audit = build_audit(
        package_id="prices", run_mode="shadow", start="2026-06", end="2026-07",
        expected=["2026-06", "2026-07"], observed=["2026-06"], sources=[],
        blockers=[{"code": "MISSING_PERIOD", "detail": "2026-07"}], unexplained_missing=["2026-07"],
    )
    assert validate_audit(audit)["passed"]
    audit["blocked"] = False
    assert not validate_audit(audit)["passed"]

def test_full_history_stays_closed_with_package_specific_blockers():
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    packages = {item["package_id"]: item for item in manifest["packages"]}
    assert all(not item["full_history_allowed"] for item in packages.values())
    assert all(len(item["full_blockers"]) >= 2 for item in packages.values())
    assert {key for key, item in packages.items() if item["shadow_state"] == "SHADOW_PASSED_SOL_REVIEW"} == {
        "pmi_state", "prices", "growth_output"
    }
    result = validate_full_entry(ROOT / "config" / "macro_w1_execution_manifest.json")
    assert result["passed"] is True
    assert result["ready_packages"] == []
    assert result["blocked_packages"] == ["rates_liquidity", "pmi_state", "prices", "money_credit", "growth_output"]
    assert result["invalid_packages"] == []
    assert result["all_packages_ready"] is False


def test_full_entry_accepts_mixed_pmi_prices_readiness(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    packages = {item["package_id"]: item for item in manifest["packages"]}
    for package_id in ("pmi_state", "prices"):
        packages[package_id]["full_history_allowed"] = True
        packages[package_id]["full_blockers"] = []
    manifest["packages"] = [packages[item["package_id"]] for item in manifest["packages"]]
    path = tmp_path / "mixed_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert result["passed"] is True
    assert result["ready_packages"] == ["pmi_state", "prices"]
    assert result["blocked_packages"] == ["rates_liquidity", "money_credit", "growth_output"]
    assert result["invalid_packages"] == []
    assert result["all_packages_ready"] is False
    assert result["full_entry_ready"] is False
    assert result["decision"] == "MIXED_PACKAGE_READINESS"
