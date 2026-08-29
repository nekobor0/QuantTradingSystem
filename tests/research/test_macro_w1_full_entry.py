import json
from pathlib import Path

from scripts.data_lake.validate_macro_w1_full_entry import validate_full_entry
from quant_trading_system.research.macro_data.w1_execution import build_audit


ROOT = Path(__file__).resolve().parents[2]


def test_w1_full_entry_has_growth_pending_with_rates_and_money_blocked():
    result = validate_full_entry(ROOT / "config" / "macro_w1_execution_manifest.json")
    assert result["passed"], result
    assert result["full_entry_ready"] is False
    assert result["decision"] == "MIXED_PACKAGE_READINESS"
    assert result["ready_packages"] == ["pmi_state", "prices", "growth_output"]
    assert result["blocked_packages"] == ["rates_liquidity", "money_credit"]


def _write_full_audit_fixtures(audit_root: Path, *, promoted_complete: bool) -> None:
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    for package in manifest["packages"]:
        package_id = package["package_id"]
        if package["full_history_allowed"]:
            blocker_details = [] if promoted_complete else ["formal full execution has not run"]
        else:
            blocker_details = package["full_blockers"]
        blockers = [
            {"code": "FULL_HISTORY_NOT_ALLOWED", "detail": detail}
            for detail in blocker_details
        ]
        audit = build_audit(
            package_id=package_id,
            run_mode="full",
            start="2009-06",
            end="2026-07",
            expected=[],
            observed=[],
            sources=[],
            blockers=blockers,
        )
        (audit_root / f"w1_{package_id}_full.json").write_text(
            json.dumps({"audit": audit}),
            encoding="utf-8",
        )


def test_promoted_packages_are_pending_before_full_execution(tmp_path: Path):
    _write_full_audit_fixtures(tmp_path, promoted_complete=False)
    result = validate_full_entry(
        ROOT / "config" / "macro_w1_execution_manifest.json",
        tmp_path,
    )
    assert result["passed"], result
    assert result["execution_pending_packages"] == ["pmi_state", "prices", "growth_output"]
    assert result["full_history_complete_packages"] == []


def test_promoted_packages_are_complete_after_full_execution(tmp_path: Path):
    _write_full_audit_fixtures(tmp_path, promoted_complete=True)
    result = validate_full_entry(
        ROOT / "config" / "macro_w1_execution_manifest.json",
        tmp_path,
    )
    assert result["passed"], result
    assert result["execution_pending_packages"] == []
    assert result["full_history_complete_packages"] == ["pmi_state", "prices", "growth_output"]


def test_pre_execution_fixture_has_only_growth_pending(tmp_path: Path) -> None:
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    for package in manifest["packages"]:
        package_id = package["package_id"]
        if package_id in {"pmi_state", "prices"}:
            blocker_details = []
        elif package_id == "growth_output":
            blocker_details = ["formal full execution has not run"]
        else:
            blocker_details = package["full_blockers"]
        audit = build_audit(
            package_id=package_id,
            run_mode="full",
            start="1992-01" if package_id == "growth_output" else "2009-06",
            end="2026-07",
            expected=[],
            observed=[],
            sources=[],
            blockers=[{"code": "FULL_HISTORY_NOT_ALLOWED", "detail": detail} for detail in blocker_details],
        )
        (tmp_path / f"w1_{package_id}_full.json").write_text(json.dumps({"audit": audit}), encoding="utf-8")
    result = validate_full_entry(
        ROOT / "config" / "macro_w1_execution_manifest.json",
        tmp_path,
    )
    assert result["passed"], result
    assert result["ready_packages"] == ["pmi_state", "prices", "growth_output"]
    assert result["execution_pending_packages"] == ["growth_output"]
    assert result["full_history_complete_packages"] == ["pmi_state", "prices"]
    assert result["blocked_packages"] == ["rates_liquidity", "money_credit"]
    assert result["full_entry_ready"] is False
    assert all(item["research_ready"] is False for item in result["audits"].values())
