import copy
import json
from pathlib import Path

import pytest

from scripts.data_lake.validate_macro_w1_global_financial_conditions_contract import (
    validate_global_financial_conditions_contract,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "config" / "macro_w1_packages" / "global_financial_conditions.json"
MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"
REGISTRY = ROOT / "config" / "macro_w1_confirmation_registry.json"


def _documents(tmp_path: Path) -> tuple[dict, dict, dict, Path, Path, Path]:
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return package, manifest, registry, tmp_path / "package.json", tmp_path / "manifest.json", tmp_path / "registry.json"


def _write(documents: tuple[dict, dict, dict, Path, Path, Path]) -> tuple[Path, Path, Path]:
    package, manifest, registry, package_path, manifest_path, registry_path = documents
    package_path.write_text(json.dumps(package), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return package_path, manifest_path, registry_path


def test_global_financial_conditions_contract_passes() -> None:
    result = validate_global_financial_conditions_contract()
    assert result["passed"], result
    assert result["series_order"] == [
        "US.EFFR", "US.SOFR", "US.TREASURY.3M", "US.TREASURY.2Y", "US.TREASURY.10Y",
        "US.TIPS.REAL.10Y", "US.BROAD_DOLLAR", "USD.CNY", "USD.CNH",
    ]
    assert result["full_history_allowed"] is False
    assert result["research_ready"] is False
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    assert package["status"] == "GOLD_BLOCKED_PARTIAL_7_OF_9"
    assert package["gold_coverage"]["ready_count"] == 7
    assert package["gold_coverage"]["missing_series"] == ["USD.CNY", "USD.CNH"]
    assert package["fx_gold_blocked_evidence"]["candidate_rows"] == 0
    assert package["fx_gold_blocked_evidence"]["candidate_parquet"] is None
    assert package["us_full_history_evidence"]["as_of_complete_series"] == package["gold_coverage"]["ready_series"]
    assert package["us_prospective_pit_evidence"]["pit_counts"] == {"PIT-A": 0, "PIT-B_PROSPECTIVE_ONLY": 7, "PIT-C": 0}
    assert package["us_prospective_pit_evidence"]["history_rows_promoted"] == 0
    assert package["us_prospective_pit_evidence"]["vintage_status"] == "observed_snapshot_only_initial_or_revised_status_not_proven"
    assert set(package["series_full_gates"]) == set(package["gold_coverage"]["ready_series"])
    assert all(gate["full_history_allowed"] is True for gate in package["series_full_gates"].values())
    assert all(gate["formal_execution_allowed"] is False for gate in package["series_full_gates"].values())


@pytest.mark.parametrize(
    "mutation",
    [
        "merge_rates",
        "drop_series",
        "swap_layer",
        "wrong_window",
        "naive_calendar",
        "wrong_treasury_field",
        "wrong_tips_basis",
        "wrong_broad_dollar_unit",
        "cny_midpoint_instead_of_close",
        "cny_entitlement_claim",
        "cnh_proxy",
        "cnh_entitlement_claim",
        "drop_regime_break",
        "drop_available_at",
        "same_day_nyfed",
        "http_date_as_available",
        "schedule_as_release",
        "claim_initial_vintage",
        "weekday_only_tradable",
        "allow_proxy",
        "allow_fill",
        "allow_overwrite",
        "allow_spread",
        "allow_shadow",
        "allow_full",
        "allow_formal",
        "mark_written",
        "research_ready",
        "manifest_remove_blocker",
        "gold_coverage_tamper",
        "broad_dollar_resolution_tamper",
        "fx_evidence_tamper",
        "manifest_fx_evidence_tamper",
        "full_evidence_tamper",
        "prospective_evidence_tamper",
        "manifest_prospective_evidence_tamper",
        "series_gate_tamper",
        "registry_full_state_tamper",
        "manifest_wrong_order",
        "registry_wrong_source",
    ],
)
def test_global_financial_conditions_contract_fails_closed(tmp_path: Path, mutation: str) -> None:
    documents = _documents(tmp_path)
    package, manifest, registry, *_ = documents
    manifest_package = next(item for item in manifest["packages"] if item["package_id"] == "global_financial_conditions")
    series = {item["series_id"]: item for item in package["series"]}
    if mutation == "merge_rates":
        package["independent_from"] = []
    elif mutation == "drop_series":
        package["series"].pop()
    elif mutation == "swap_layer":
        package["layers"]["FXConstraint"] = ["US.BROAD_DOLLAR", "USD.CNY", "USD.CNH"]
    elif mutation == "wrong_window":
        package["series_windows"]["US.SOFR"]["start"] = "2018-04-03"
    elif mutation == "naive_calendar":
        package["series_windows"]["US.EFFR"]["calendar"] = "weekdays"
    elif mutation == "wrong_treasury_field":
        series["US.TREASURY.10Y"]["official_field"] = "TC_10YEAR"
    elif mutation == "wrong_tips_basis":
        series["US.TIPS.REAL.10Y"]["measure_basis"] = "nominal_yield"
    elif mutation == "wrong_broad_dollar_unit":
        series["US.BROAD_DOLLAR"]["unit"] = "percent"
    elif mutation == "cny_midpoint_instead_of_close":
        series["USD.CNY"]["official_field"] = "USD_CNY_CENTRAL_PARITY"
    elif mutation == "cny_entitlement_claim":
        series["USD.CNY"]["license_scope"] = "internal_research"
    elif mutation == "cnh_proxy":
        series["USD.CNH"]["official_field"] = "USD_CNY_1630_SPOT_CLOSE"
    elif mutation == "cnh_entitlement_claim":
        series["USD.CNH"]["license_scope"] = "internal_research"
    elif mutation == "drop_regime_break":
        package["required_regime_breaks"].pop("UST_2021_12_06_MONOTONE_CONVEX_METHOD")
    elif mutation == "drop_available_at":
        package["pit_asof_policy"].pop("available_at_rule")
    elif mutation == "same_day_nyfed":
        package["pit_asof_policy"]["nyfed_initial_publication"]["EFFR"] = "same reference day"
    elif mutation == "http_date_as_available":
        package["pit_asof_policy"]["retrieval_timestamp_rule"] = "HTTP Date is available_at"
    elif mutation == "schedule_as_release":
        package["pit_asof_policy"]["schedule_evidence_rule"] = "fixed schedules establish release_at"
    elif mutation == "claim_initial_vintage":
        package["pit_asof_policy"]["observed_vintage_rule"] = "all first captures are initial vintages"
    elif mutation == "weekday_only_tradable":
        package["pit_asof_policy"]["tradable_calendar_rule"] = "use next weekday"
    elif mutation == "allow_proxy":
        package["candidate_rules"]["proxy_series_allowed"] = True
    elif mutation == "allow_fill":
        package["candidate_rules"]["forward_fill_allowed"] = True
    elif mutation == "allow_overwrite":
        package["candidate_rules"]["initial_and_revised_vintages_may_overwrite"] = True
    elif mutation == "allow_spread":
        package["candidate_rules"]["cny_cnh_spread_allowed_before_matched_timestamp_proof"] = True
    elif mutation == "allow_shadow":
        package["shadow_allowed"] = True
    elif mutation == "allow_full":
        package["full_history_allowed"] = True
    elif mutation == "allow_formal":
        package["formal_execution_allowed"] = True
    elif mutation == "mark_written":
        package["formal_curated_written"] = True
    elif mutation == "research_ready":
        package["research_ready"] = True
    elif mutation == "manifest_remove_blocker":
        manifest_package["full_blockers"].pop()
    elif mutation == "gold_coverage_tamper":
        package["gold_coverage"]["ready_count"] = 9
    elif mutation == "broad_dollar_resolution_tamper":
        package["gold_candidate_evidence"]["broad_dollar_metadata_resolution"]["old_goods_only_broad_index_forbidden"] = False
    elif mutation == "fx_evidence_tamper":
        package["fx_gold_blocked_evidence"]["candidate_rows"] = 1
    elif mutation == "manifest_fx_evidence_tamper":
        manifest_package["fx_gold_blocked_evidence"]["candidate_rows"] = 1
    elif mutation == "full_evidence_tamper":
        package["us_full_history_evidence"]["structural_omissions"]["US.TREASURY.3M"] = []
    elif mutation == "prospective_evidence_tamper":
        package["us_prospective_pit_evidence"]["history_rows_promoted"] = 47276
    elif mutation == "manifest_prospective_evidence_tamper":
        manifest_package["us_prospective_pit_evidence"]["gate_promotion"] = True
    elif mutation == "series_gate_tamper":
        package["series_full_gates"]["US.EFFR"]["formal_execution_allowed"] = True
    elif mutation == "registry_full_state_tamper":
        item = next(item for item in registry["series"] if item["canonical_id"] == "US.EFFR")
        item["state"] = "GOLD_READY_FROZEN_CANDIDATE_PIT_C"
    elif mutation == "manifest_wrong_order":
        manifest_package["order"] = 5
    elif mutation == "registry_wrong_source":
        item = next(item for item in registry["series"] if item["canonical_id"] == "US.EFFR")
        item["source"] = "US_TREASURY"
    paths = _write((copy.deepcopy(package), manifest, registry, *documents[3:]))
    result = validate_global_financial_conditions_contract(*paths)
    assert not result["passed"], mutation
