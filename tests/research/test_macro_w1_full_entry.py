import json
from pathlib import Path

import pytest

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


def test_rates_cannot_be_promoted_to_full_history(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    rates = next(item for item in manifest["packages"] if item["package_id"] == "rates_liquidity")
    rates["full_history_allowed"] = True
    rates["full_blockers"] = []
    rates["full_window"] = {"start": "2006-10", "end": "2026-08", "scope": "official_history"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "rates_liquidity" in result["invalid_packages"]
    assert "rates_liquidity" not in result["ready_packages"]


@pytest.mark.parametrize("execution_complete", [False, True])
def test_rates_cannot_be_placed_in_pending_or_complete(tmp_path: Path, execution_complete: bool):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    rates = next(item for item in manifest["packages"] if item["package_id"] == "rates_liquidity")
    rates["full_history_allowed"] = True
    rates["full_blockers"] = []
    rates["full_window"] = {"start": "2006-10", "end": "2026-08", "scope": "official_history"}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _write_full_audit_fixtures(tmp_path, promoted_complete=True)
    blockers = [] if execution_complete else [{"code": "FULL_HISTORY_NOT_ALLOWED", "detail": "formal full execution has not run"}]
    audit = build_audit(
        package_id="rates_liquidity",
        run_mode="full",
        start="2006-10",
        end="2026-08",
        expected=[],
        observed=[],
        sources=[],
        blockers=blockers,
    )
    (tmp_path / "w1_rates_liquidity_full.json").write_text(json.dumps({"audit": audit}), encoding="utf-8")
    result = validate_full_entry(manifest_path, tmp_path)
    assert not result["passed"]
    assert "rates_liquidity" in result["invalid_packages"]
    target = result["full_history_complete_packages"] if execution_complete else result["execution_pending_packages"]
    assert "rates_liquidity" in target


def test_rates_rejects_missing_full_history_blocker(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    rates = next(item for item in manifest["packages"] if item["package_id"] == "rates_liquidity")
    rates["full_blockers"] = rates["full_blockers"][1:]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "rates_liquidity" in result["invalid_packages"]


def test_rates_rejects_research_ready_true(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    rates = next(item for item in manifest["packages"] if item["package_id"] == "rates_liquidity")
    rates["research_ready"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "rates_liquidity" in result["invalid_packages"]


def test_rates_rejects_formal_curated_written_true(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    rates = next(item for item in manifest["packages"] if item["package_id"] == "rates_liquidity")
    rates["formal_curated_written"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "rates_liquidity" in result["invalid_packages"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gold_state", "GOLD_BLOCKED_PARTIAL_5_OF_8"),
        ("full_history_allowed", True),
        ("formal_curated_written", True),
        ("research_ready", True),
    ],
)
def test_money_rejects_premature_promotion(tmp_path: Path, field: str, value: object):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    money = next(item for item in manifest["packages"] if item["package_id"] == "money_credit")
    money[field] = value
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]


def test_money_rejects_afre_full_history_blocker_removal(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    money = next(item for item in manifest["packages"] if item["package_id"] == "money_credit")
    money["full_blockers"] = [item for item in money["full_blockers"] if "AFRE" not in item]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]


def test_money_rejects_afre_gold_coverage_rollback(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    money = next(item for item in manifest["packages"] if item["package_id"] == "money_credit")
    money["gold_coverage"]["ready_count"] = 5
    money["gold_coverage"]["missing_series"].append("CN.TSF.RMB_LOANS.FLOW")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert not result["passed"]
    assert "money_credit" in result["invalid_packages"]
