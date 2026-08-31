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

def test_pmi_prices_and_growth_full_history_are_allowed_with_two_packages_blocked():
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    packages = {item["package_id"]: item for item in manifest["packages"]}
    assert {key for key, item in packages.items() if item["full_history_allowed"]} == {"pmi_state", "prices", "growth_output"}
    assert all(packages[key]["full_blockers"] == [] for key in ("pmi_state", "prices", "growth_output"))
    assert len(packages["rates_liquidity"]["full_blockers"]) == 1
    assert len(packages["money_credit"]["full_blockers"]) >= 2
    assert packages["rates_liquidity"]["gold_state"] == "GOLD_READY_11_OF_11_FULL_HISTORY_BLOCKED_CFETS"
    assert packages["rates_liquidity"]["gold_coverage"] == {
        "ready_count": 11,
        "required_count": 11,
        "missing_series": [],
    }
    chinabond = packages["rates_liquidity"]["series_history_evidence"]["chinabond_government_ytm"]
    assert chinabond["history_evidence_complete"] is True
    assert chinabond["formal_execution_allowed"] is False
    assert chinabond["formal_curated_written"] is False
    assert chinabond["research_ready"] is False
    assert chinabond["full_window"]["observed_rows"] == 12318
    assert chinabond["full_window"]["pit_grade"] == "C"
    assert packages["rates_liquidity"]["shadow_allowed"] is False
    assert packages["rates_liquidity"]["full_history_allowed"] is False
    assert packages["rates_liquidity"]["formal_curated_written"] is False
    assert packages["rates_liquidity"]["research_ready"] is False
    assert packages["money_credit"]["gold_state"] == "GOLD_READY_ACTIVE_6_OF_6"
    assert packages["money_credit"]["gold_coverage"] == {
        "ready_count": 6,
        "required_count": 6,
        "missing_series": [],
    }
    assert packages["money_credit"]["retired_not_required_series"] == [
        "CN.LOANS.RMB.FLOW", "CN.LOANS.CORP.MEDIUM_LONG.FLOW"
    ]
    assert packages["money_credit"]["shadow_allowed"] is False
    assert packages["money_credit"]["formal_curated_written"] is False
    assert packages["money_credit"]["formal_state_scope"] == "package_level"
    assert packages["money_credit"]["formal_execution_state"] == "NOT_BUILT"
    assert packages["money_credit"]["research_ready"] is False
    afre_gate = packages["money_credit"]["series_full_gates"]["CN.TSF.RMB_LOANS.FLOW"]
    assert afre_gate["full_history_allowed"] is True
    assert afre_gate["formal_execution_state"] == "COMPLETE"
    assert afre_gate["formal_curated_written"] is True
    assert afre_gate["research_ready"] is False
    assert afre_gate["full_window"] == {
        "start": "2002-01",
        "end": "2026-07",
        "scope": "official_direct_monthly_observations_with_explained_source_structural_omission",
        "calendar_rows": 295,
        "observed_rows": 294,
        "structural_omissions": ["2025-12"],
    }
    assert {key for key, item in packages.items() if item["shadow_state"] == "SHADOW_PASSED_SOL_REVIEW"} == {
        "pmi_state", "prices", "growth_output"
    }
    result = validate_full_entry(ROOT / "config" / "macro_w1_execution_manifest.json")
    assert result["passed"] is True
    assert result["ready_packages"] == ["pmi_state", "prices", "growth_output"]
    assert result["blocked_packages"] == ["rates_liquidity", "money_credit", "global_financial_conditions"]
    assert result["invalid_packages"] == []
    assert result["all_packages_ready"] is False


def test_money_contract_has_matching_series_level_afre_gate():
    package = json.loads((ROOT / "config" / "macro_w1_packages" / "money_credit.json").read_text(encoding="utf-8"))
    gate = package["afre_full_history_gate"]
    assert gate["series_id"] == "CN.TSF.RMB_LOANS.FLOW"
    assert gate["status"] == "FULL_HISTORY_COMPLETE_WITH_EXPLAINED_STRUCTURAL_OMISSION"
    assert gate["full_history_allowed"] is True
    assert gate["formal_execution_state"] == "COMPLETE"
    assert gate["formal_curated_written"] is True
    assert gate["research_ready"] is False
    assert gate["window"]["calendar_rows"] == 295
    assert gate["window"]["observed_rows"] == 294
    assert gate["window"]["structural_omissions"] == ["2025-12"]
    assert gate["formal_input"]["candidate_sha256"] == "04098A0763418B5873CDA6808363805FA3ED8DB7EFB0178B25B896D621469A64"
    assert gate["formal_input"]["candidate_audit_sha256"] == "7E521148DB8C26043E0D6984722A27E585D37C4785D37040A01D5DA53B743A0C"
    assert gate["formal_output"]["formal_curated_sha256"] == "04098A0763418B5873CDA6808363805FA3ED8DB7EFB0178B25B896D621469A64"
    assert gate["formal_output"]["formal_audit_sha256"] == "14C6C03DD2565C3114E388AA62C0606AE4B7FADAAFEE693DDF96B436F531F619"
    assert package["formal_curated_written"] is False
    assert package["formal_state_scope"] == "package_level"
    assert package["formal_execution_state"] == "NOT_BUILT"
    assert package["pending_full_history_contract"]["calendar_rows_total"] == 1165
    assert package["pending_full_history_contract"]["series_order"] == [
        "CN.MONEY.M1.BALANCE",
        "CN.MONEY.M2.BALANCE",
        "CN.TSF.FLOW",
        "CN.TSF.STOCK",
        "CN.TSF.GOV_BOND.FLOW",
    ]
    assert package["status"] == "GOLD_READY_ACTIVE_6_OF_6"
    assert package["gold_coverage"]["required_count"] == 6
    assert package["gold_coverage"]["missing_series"] == []
    assert package["canonical_scope_policy"]["derived_replacement_implemented"] is False
    assert package["canonical_scope_policy"]["cumulative_differencing_allowed"] is False
    assert package["canonical_scope_policy"]["balance_differencing_allowed"] is False


def test_rates_contract_has_frozen_chinabond_pit_c_evidence() -> None:
    package = json.loads((ROOT / "config" / "macro_w1_packages" / "rates_liquidity.json").read_text(encoding="utf-8"))
    assert package["status"] == "GOLD_READY_11_OF_11_FULL_HISTORY_BLOCKED_CFETS"
    assert package["gold_coverage"]["ready_count"] == 11
    assert package["gold_coverage"]["missing_series"] == []
    assert package["full_history_blocked_series"] == ["CN.REPO.DR007", "CN.REPO.R007"]
    evidence = package["chinabond_full_history_evidence"]
    assert evidence["history_evidence_complete"] is True
    assert evidence["formal_execution_allowed"] is False
    assert evidence["formal_curated_written"] is False
    assert evidence["research_ready"] is False
    assert evidence["window"]["observed_rows"] == 12318
    assert evidence["window"]["pit_grade"] == "C"
    series = {item["series_id"]: item for item in package["series"]}
    for series_id in ("CN.CHINABOND.GOV.YTM.1Y", "CN.CHINABOND.GOV.YTM.10Y"):
        assert series[series_id]["pit_grade"] == "C"
        assert series[series_id]["license_scope"] == "user_provided_internal_research"
        assert series[series_id]["implementation"] == "FULL_HISTORY_EVIDENCE_ACCEPTED_PIT_C"


def test_full_entry_accepts_one_ready_package_when_prices_is_temporarily_blocked(tmp_path: Path):
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    packages = {item["package_id"]: item for item in manifest["packages"]}
    packages["prices"]["full_history_allowed"] = False
    packages["prices"]["full_blockers"] = ["temporary test blocker"]
    manifest["packages"] = [packages[item["package_id"]] for item in manifest["packages"]]
    path = tmp_path / "mixed_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_full_entry(path)
    assert result["passed"] is True
    assert result["ready_packages"] == ["pmi_state", "growth_output"]
    assert result["blocked_packages"] == ["rates_liquidity", "prices", "money_credit", "global_financial_conditions"]
    assert result["invalid_packages"] == []
    assert result["all_packages_ready"] is False
    assert result["full_entry_ready"] is False
    assert result["decision"] == "MIXED_PACKAGE_READINESS"
