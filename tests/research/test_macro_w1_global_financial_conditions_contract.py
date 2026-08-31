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
        "cnh_proxy",
        "cnh_entitlement_claim",
        "drop_regime_break",
        "drop_available_at",
        "same_day_nyfed",
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
    elif mutation == "manifest_wrong_order":
        manifest_package["order"] = 5
    elif mutation == "registry_wrong_source":
        item = next(item for item in registry["series"] if item["canonical_id"] == "US.EFFR")
        item["source"] = "US_TREASURY"
    paths = _write((copy.deepcopy(package), manifest, registry, *documents[3:]))
    result = validate_global_financial_conditions_contract(*paths)
    assert not result["passed"], mutation
