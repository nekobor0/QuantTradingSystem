"""Validate the frozen global-financial-conditions contract without acquiring data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = ROOT / "config" / "macro_w1_packages" / "global_financial_conditions.json"
DEFAULT_MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"
DEFAULT_REGISTRY = ROOT / "config" / "macro_w1_confirmation_registry.json"

SERIES_ORDER = [
    "US.EFFR",
    "US.SOFR",
    "US.TREASURY.3M",
    "US.TREASURY.2Y",
    "US.TREASURY.10Y",
    "US.TIPS.REAL.10Y",
    "US.BROAD_DOLLAR",
    "USD.CNY",
    "USD.CNH",
]
LAYERS = {
    "DomesticLiquidity": ["US.EFFR", "US.SOFR"],
    "GlobalUSDConditions": [
        "US.TREASURY.3M",
        "US.TREASURY.2Y",
        "US.TREASURY.10Y",
        "US.TIPS.REAL.10Y",
        "US.BROAD_DOLLAR",
    ],
    "FXConstraint": ["USD.CNY", "USD.CNH"],
}
SOURCES = ["NYFED_MARKETS", "US_TREASURY", "FEDERAL_RESERVE_H10", "CFETS_CHINAMONEY"]
DECISIONS = ["GFC_D1", "GFC_D2", "GFC_D3", "GFC_D4", "GFC_D5", "GFC_D6"]
WINDOWS = {
    "US.EFFR": ("2000-07-03", "nyfed_unsecured_reference_rate_business_days"),
    "US.SOFR": ("2018-04-02", "sifma_us_government_securities_business_days"),
    "US.TREASURY.3M": ("1990-01-02", "us_treasury_trading_days"),
    "US.TREASURY.2Y": ("1990-01-02", "us_treasury_trading_days"),
    "US.TREASURY.10Y": ("1990-01-02", "us_treasury_trading_days"),
    "US.TIPS.REAL.10Y": ("2003-01-02", "us_treasury_real_curve_trading_days"),
    "US.BROAD_DOLLAR": ("2006-01-02", "federal_reserve_h10_observation_days"),
    "USD.CNY": ("2015-08-24", "cfets_fx_trading_days"),
    "USD.CNH": ("2010-08-23", "offshore_rmb_trading_days"),
}
REGIME_BREAKS = {
    "EFFR_2016_03_01_FR2420_METHOD_CHANGE": ["US.EFFR"],
    "SOFR_2018_04_02_SERIES_START": ["US.SOFR"],
    "SOFR_2024_11_25_METHOD_CHANGE": ["US.SOFR"],
    "UST_2021_12_06_MONOTONE_CONVEX_METHOD": ["US.TREASURY.3M", "US.TREASURY.2Y", "US.TREASURY.10Y"],
    "TIPS_2004_PUBLICATION_WITH_2003_HISTORY": ["US.TIPS.REAL.10Y"],
    "BROAD_DOLLAR_2019_INDEX_REVISION": ["US.BROAD_DOLLAR"],
    "CNY_2015_08_11_FIXING_REFORM": ["USD.CNY"],
    "CNY_2023_01_03_EXTENDED_TRADING_HOURS_CLOSE_UNCHANGED": ["USD.CNY"],
    "CNH_OFFICIAL_SOURCE_REGIME_UNRESOLVED": ["USD.CNH"],
}
SERIES_FIELDS = {
    "US.EFFR": ("NYFED_MARKETS", "percentRate", "percent_per_annum", "overnight_unsecured_transaction_volume_weighted_median"),
    "US.SOFR": ("NYFED_MARKETS", "percentRate", "percent_per_annum", "overnight_treasury_repo_transaction_volume_weighted_median"),
    "US.TREASURY.3M": ("US_TREASURY", "BC_3MONTH", "percent_per_annum", "daily_par_yield_curve"),
    "US.TREASURY.2Y": ("US_TREASURY", "BC_2YEAR", "percent_per_annum", "daily_par_yield_curve"),
    "US.TREASURY.10Y": ("US_TREASURY", "BC_10YEAR", "percent_per_annum", "daily_par_yield_curve"),
    "US.TIPS.REAL.10Y": ("US_TREASURY", "TC_10YEAR", "percent_per_annum_real", "daily_par_real_yield_curve"),
    "US.BROAD_DOLLAR": ("FEDERAL_RESERVE_H10", "H10/H10/JRXWTFB_N.B", "index_2006_100", "nominal_trade_weighted_broad_dollar_index"),
    "USD.CNY": ("CFETS_CHINAMONEY", "USD_CNY_1630_SPOT_CLOSE", "cny_per_usd", "official_interbank_spot_closing_price_1630"),
    "USD.CNH": ("CFETS_CHINAMONEY", "UNRESOLVED_OFFICIAL_USD_CNH_SPOT_CLOSE", "cnh_per_usd", "offshore_spot_close_target_matched_timestamp"),
}
MANIFEST_BLOCKERS = [
    "USD.CNY official 16:30 close product is confirmed, but the public historical field is unavailable and member-interface entitlement is not established",
    "USD.CNH exact official historical source, matched observation time, and entitlement remain unresolved",
    "the seven US series have accepted series-level PIT-C evidence only; package formal aggregation is not built or authorized",
    "PIT-A release vintages have not been captured and validated",
]
FX_EVIDENCE_HASHES = {
    "candidate_audit": "CE3E0745875C1F4A2E9580D12BBE3BA7013917F9ECB0BA75CD70D507D1104BF8",
    "source_map.json": "FE394C1B8A999DABAF54C5A16783DA2AEFF7BCB98E3B305627A8A33518A1C08C",
    "manual_audit.json": "AF6266A823AA22E8A8318E7A995627BDEF40D090CB768D3E60A9F79F5F7E7099",
    "request_evidence_log.json": "DED720E9313D2D0AF5A6EC283D15EEEE054F422BB137715C9AA76CC3D275B3F9",
    "raw_manifest.json": "9C91B6359DF2F79DDA3BBB8652FA1208EC11E14C2F993314ABD4FC6B4AB2FE1A",
}
FX_BLOCKED_EVIDENCE = {
    "status": "BLOCKED_NO_ACCEPTED_OFFICIAL_ROWS",
    "requested_window": ["2026-08-20", "2026-08-21"],
    "candidate_rows": 0,
    "candidate_parquet": None,
    "passed_series": [],
    "blocked_series": ["USD.CNY", "USD.CNH"],
    "pit_counts": {"PIT-A": 0, "PIT-C": 0},
    "frozen_sha256": FX_EVIDENCE_HASHES,
    "usd_cny_resolution": "official_1630_close_product_confirmed_but_public_historical_field_unavailable_and_member_interface_entitlement_not_established",
    "usd_cnh_resolution": "official_historical_source_matched_observation_time_and_entitlement_unresolved",
    "diagnostic_values_are_not_candidate_evidence": True,
}
READY_SERIES = SERIES_ORDER[:7]
MISSING_SERIES = SERIES_ORDER[7:]
GOLD_COVERAGE = {
    "ready_count": 7,
    "required_count": 9,
    "ready_series": READY_SERIES,
    "missing_series": MISSING_SERIES,
}
GOLD_EVIDENCE_HASHES = {
    "candidate_canonical_v2.parquet": "7738CDF057CE7E6F7E1653CA805A0CC6EDD3B54A8EEFED9EBD4D2F3237BCBBD0",
    "expected.json": "1458D90A0CBA56C773C057991F903C34432AFEFC94D0444B5254EA3644109351",
    "source_map.json": "A5BA0561322E21A603322343E1C449AE664E4F2A229C62DF27A65D5D9634E0FC",
    "manual_audit.json": "32A9AE58857AC1FBDE471D05948E48860CB6F41D3CF2BCD7A37AA9572238B61F",
    "raw_manifest.json": "293A68F380CD036F2A7CAF6B76C702C80A9C107FD4651AADCE9F6C7F29407231",
    "candidate_audit": "E5F0CF2AB6192C4CE8330DBC28FB8D7DA6AA342864DE76CB4D7452BDFCB234C0",
}
US_FULL_EVIDENCE_SUMMARY = {
    "status": "SOL_ACCEPTED_AS_OF_COMPLETE_PIT_C_7_US_SERIES",
    "candidate_rows": 47276,
    "candidate_sha256": "FDC500EFAB0DCAD9C5F077FC9FA29DFD97DA1802D13F7C57B64C0EE232F57FEA",
    "candidate_audit_sha256": "4B0E424E2204ABF7745E3A75BBACE2DC5DD02B4CB8A363FF36936F668E6B6751",
    "pit_counts": {"PIT-A": 0, "PIT-C": 47276},
    "fixed_contract_complete_series": ["US.TREASURY.3M", "US.TREASURY.2Y", "US.TREASURY.10Y", "US.TIPS.REAL.10Y"],
    "as_of_complete_series": READY_SERIES,
    "publication_lag_pending_series": ["US.EFFR", "US.SOFR", "US.BROAD_DOLLAR"],
    "structural_omission_series": ["US.TREASURY.3M"],
    "official_calendar_exception_series": ["US.EFFR"],
}
PROSPECTIVE_EVIDENCE_HASHES = {
    "evidence_matrix.json": "67B792AB2DF6063DC05D9F5CD192DDD8EC6FD5C0F000F7AC3D9DE8434C48579C",
    "request_evidence_log.json": "833D04D43E9C031E767B1F71E26071A9100A18FDABC456EDF860870AFF4A8658",
    "reverse_validation.json": "1C93999D22D9E6AD45300D7C3A75BDF583B4E6C1C002D9D6E204741EA266D474",
    "source_map.json": "B62EE8340DE33EE1323BC6849DC95BF572ACA5F99B9FB33499E948EFFEE0B7FE",
    "candidate_audit": "3B89CE8ABD77A96A133A79F3F1ACB2C7DE33A0AA49444815344B081A432C457D",
    "raw_manifest.json": "7A4C7066363EADC5CBACA9E05A2B30A3E545F86F19A7B6A3E1A7A65BF20C85FB",
}
SERIES_GATE_STATUS = {
    series_id: (
        "AS_OF_FULL_HISTORY_EVIDENCE_ACCEPTED_PIT_C_FORMAL_NOT_AUTHORIZED"
        if series_id in {"US.EFFR", "US.SOFR", "US.BROAD_DOLLAR"}
        else "FULL_HISTORY_EVIDENCE_ACCEPTED_PIT_C_FORMAL_NOT_AUTHORIZED"
    )
    for series_id in READY_SERIES
}


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validate_global_financial_conditions_contract(
    package_path: Path = DEFAULT_PACKAGE,
    manifest_path: Path = DEFAULT_MANIFEST,
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    package = _load(package_path)
    manifest = _load(manifest_path)
    registry = _load(registry_path)
    if package is None or manifest is None or registry is None:
        return {"passed": False, "checks": {"documents_readable": False}, "failures": ["DOCUMENT_UNREADABLE"]}

    manifest_matches = [
        item for item in manifest.get("packages", [])
        if isinstance(item, dict) and item.get("package_id") == "global_financial_conditions"
    ]
    manifest_package = manifest_matches[0] if len(manifest_matches) == 1 else {}
    series = package.get("series")
    series_by_id = {
        item.get("series_id"): item for item in series if isinstance(item, dict)
    } if isinstance(series, list) else {}
    windows = package.get("series_windows")
    pit = package.get("pit_asof_policy")
    rules = package.get("candidate_rules")
    registered = {
        item.get("canonical_id"): item for item in registry.get("series", []) if isinstance(item, dict)
    }

    window_exact = isinstance(windows, dict) and list(windows) == SERIES_ORDER and all(
        windows[series_id].get("start") == start
        and windows[series_id].get("end") == "2026-08-28"
        and windows[series_id].get("calendar") == calendar
        for series_id, (start, calendar) in WINDOWS.items()
    )
    metadata_exact = list(series_by_id) == SERIES_ORDER and all(
        (
            series_by_id[series_id].get("source"),
            series_by_id[series_id].get("official_field"),
            series_by_id[series_id].get("unit"),
            series_by_id[series_id].get("measure_basis"),
        ) == SERIES_FIELDS[series_id]
        and series_by_id[series_id].get("frequency") == "business_daily"
        and all(series_by_id[series_id].get(field) for field in ("pit_grade", "license_scope", "implementation"))
        for series_id in SERIES_ORDER
    )
    fail_closed_states = all(
        package.get(field) is False
        for field in (
            "gold_ready",
            "shadow_allowed",
            "full_history_allowed",
            "formal_execution_allowed",
            "formal_curated_written",
            "research_ready",
        )
    ) and package.get("candidate_only") is True
    no_proxy_fill = isinstance(rules, dict) and all(
        rules.get(field) is False
        for field in (
            "duplicate_primary_keys_allowed",
            "interpolation_allowed",
            "zero_fill_allowed",
            "forward_fill_allowed",
            "proxy_series_allowed",
            "initial_and_revised_vintages_may_overwrite",
            "naive_weekday_calendar_allowed",
            "cny_cnh_spread_allowed_before_matched_timestamp_proof",
        )
    ) and rules.get("official_source_only") is True and rules.get("raw_sha256_required") is True and rules.get("partial_evidence_cannot_promote_gate") is True
    pit_exact = isinstance(pit, dict) and all(
        key in pit
        for key in (
            "reference_period_rule",
            "release_at_rule",
            "available_at_rule",
            "tradable_at_rule",
            "pit_b_prospective_only_rule",
            "retrieval_timestamp_rule",
            "schedule_evidence_rule",
            "observed_vintage_rule",
            "tradable_calendar_rule",
            "retrospective_history_without_release_evidence",
            "nyfed_initial_publication",
            "nyfed_revision_cutoff",
            "treasury_publication",
            "broad_dollar_publication",
            "usd_cny_publication",
            "usd_cnh_publication",
            "cross_market_alignment",
        )
    ) and all(pit.get(key) == value for key, value in {
        "pit_b_prospective_only_rule": "an immutable official snapshot with completed-response retrieval recorded as available_at; usable only at or after a holiday-aware tradable_at; proves neither earlier availability nor initial/revised status and never promotes history",
        "retrieval_timestamp_rule": "available_at uses completed response retrieval in UTC; requested_at and HTTP Date are transport evidence only",
        "schedule_evidence_rule": "official approximate or fixed schedules describe expected publication timing but never by themselves establish an observation release_at",
        "observed_vintage_rule": "label a capture as observed_snapshot unless direct evidence proves initial or revised status; every later changed capture receives a distinct immutable vintage_id and never overwrites",
        "tradable_calendar_rule": "next eligible strategy decision time requires the official holiday and trading calendar; naive next-weekday logic is insufficient",
    }.items()) and pit.get("retrospective_history_without_release_evidence") == "PIT_C_EXPLORATORY_ONLY" and pit.get("nyfed_initial_publication") == {
        "EFFR": "approximately 09:00 America/New_York on the next NYFed business day",
        "SOFR": "approximately 08:00 America/New_York on the next SIFMA business day",
    } and pit.get("nyfed_revision_cutoff") == "approximately 14:30 America/New_York on the publication day; initial and revised observations require distinct immutable vintages"
    fx_boundary = (
        series_by_id.get("USD.CNY", {}).get("official_field") == "USD_CNY_1630_SPOT_CLOSE"
        and series_by_id.get("USD.CNY", {}).get("measure_basis") == "official_interbank_spot_closing_price_1630"
        and series_by_id.get("USD.CNY", {}).get("pit_grade") == "C_ACCESS_BLOCKED_NO_ACCEPTED_ROWS"
        and series_by_id.get("USD.CNY", {}).get("license_scope") == "member_interface_entitlement_not_established"
        and series_by_id.get("USD.CNY", {}).get("implementation") == "OFFICIAL_PRODUCT_CONFIRMED_ENTITLEMENT_BLOCKED"
        and series_by_id.get("USD.CNH", {}).get("implementation") == "SOURCE_AND_ENTITLEMENT_BLOCKED"
        and series_by_id.get("USD.CNH", {}).get("license_scope") == "entitlement_unresolved"
    )
    evidence = package.get("gold_candidate_evidence")
    fx_evidence = package.get("fx_gold_blocked_evidence")
    gold_evidence_exact = (
        package.get("gold_coverage") == GOLD_COVERAGE
        and isinstance(evidence, dict)
        and evidence.get("status") == "SOL_ACCEPTED_PIT_C_GOLD_7_OF_9"
        and evidence.get("candidate_rows") == 14
        and evidence.get("reference_dates") == ["2026-08-20", "2026-08-21"]
        and evidence.get("pit_counts") == {"PIT-A": 0, "PIT-C": 14}
        and evidence.get("frozen_sha256") == GOLD_EVIDENCE_HASHES
        and evidence.get("broad_dollar_metadata_resolution") == {
            "canonical_unit": "index_2006_100",
            "official_series": "H10/H10/JRXWTFB_N.B",
            "preview_label": "Index:_1997_Jan_100",
            "resolution": "official_preview_label_conflicts_with_post_2019_H10_methodology; values accepted without rescaling as the post-2019 nominal broad dollar index indexed to January 2006",
            "old_goods_only_broad_index_forbidden": True,
        }
        and all(series_by_id[series_id].get("pit_grade") == "C_FULL_HISTORY_EVIDENCE_ACCEPTED"
                and series_by_id[series_id].get("implementation") == "FULL_HISTORY_EVIDENCE_ACCEPTED_PIT_C_FORMAL_NOT_AUTHORIZED"
                for series_id in READY_SERIES)
        and fx_evidence == FX_BLOCKED_EVIDENCE
    )
    prospective_evidence = package.get("us_prospective_pit_evidence")
    prospective_evidence_exact = (
        isinstance(prospective_evidence, dict)
        and prospective_evidence.get("status") == "SOL_ACCEPTED_PIT_B_PROSPECTIVE_ONLY_7_US_SNAPSHOTS"
        and prospective_evidence.get("scope") == "captured_snapshots_only_no_historical_promotion"
        and prospective_evidence.get("series") == READY_SERIES
        and prospective_evidence.get("pit_counts") == {"PIT-A": 0, "PIT-B_PROSPECTIVE_ONLY": 7, "PIT-C": 0}
        and prospective_evidence.get("release_at") is None
        and prospective_evidence.get("available_at_basis") == "completed official-response retrieval timestamp in UTC"
        and prospective_evidence.get("vintage_status") == "observed_snapshot_only_initial_or_revised_status_not_proven"
        and prospective_evidence.get("history_rows_promoted") == 0
        and prospective_evidence.get("gate_promotion") is False
        and prospective_evidence.get("frozen_sha256") == PROSPECTIVE_EVIDENCE_HASHES
    )
    series_gates = package.get("series_full_gates")
    full_evidence = package.get("us_full_history_evidence")
    series_full_evidence_exact = (
        isinstance(series_gates, dict)
        and set(series_gates) == set(READY_SERIES)
        and all(series_gates[series_id].get("status") == SERIES_GATE_STATUS[series_id]
                and series_gates[series_id].get("full_history_allowed") is True
                and all(series_gates[series_id].get(field) is False for field in ("formal_execution_allowed", "formal_curated_written", "research_ready"))
                for series_id in READY_SERIES)
        and isinstance(full_evidence, dict)
        and full_evidence.get("status") == US_FULL_EVIDENCE_SUMMARY["status"]
        and full_evidence.get("candidate_rows") == 47276
        and full_evidence.get("pit_counts") == {"PIT-A": 0, "PIT-C": 47276}
        and full_evidence.get("fixed_contract_complete_series") == US_FULL_EVIDENCE_SUMMARY["fixed_contract_complete_series"]
        and full_evidence.get("as_of_complete_series") == READY_SERIES
        and full_evidence.get("publication_lag_pending_series") == US_FULL_EVIDENCE_SUMMARY["publication_lag_pending_series"]
        and full_evidence.get("structural_omissions", {}).get("US.TREASURY.3M") == ["2008-12-10", "2008-12-18", "2008-12-24"]
        and full_evidence.get("official_calendar_exceptions", {}).get("US.EFFR", [{}])[0].get("reference_period") == "2003-07-20"
    )
    manifest_exact = (
        manifest.get("as_of") == "2026-08-31"
        and len(manifest_matches) == 1
        and manifest_package.get("order") == 6
        and manifest_package.get("gold_state") == "GOLD_BLOCKED_PARTIAL_7_OF_9"
        and manifest_package.get("gold_coverage") == {"ready_count": 7, "required_count": 9, "missing_series": MISSING_SERIES}
        and manifest_package.get("shadow_state") == "GOLD_PARTIAL_7_OF_9_NO_PACKAGE_SHADOW"
        and manifest_package.get("contract_id") == "R011.W1.GLOBAL_FINANCIAL_CONDITIONS.V1"
        and manifest_package.get("series_count") == 9
        and manifest_package.get("independent_from") == ["rates_liquidity"]
        and manifest_package.get("layers") == list(LAYERS)
        and manifest_package.get("fx_gold_blocked_evidence") == {
            "status": "BLOCKED_NO_ACCEPTED_OFFICIAL_ROWS",
            "candidate_rows": 0,
            "candidate_audit_sha256": FX_EVIDENCE_HASHES["candidate_audit"],
            "raw_manifest_sha256": FX_EVIDENCE_HASHES["raw_manifest.json"],
            "blocked_series": MISSING_SERIES,
        }
        and manifest_package.get("us_full_history_evidence") == US_FULL_EVIDENCE_SUMMARY
        and manifest_package.get("us_prospective_pit_evidence") == {
            "status": "SOL_ACCEPTED_PIT_B_PROSPECTIVE_ONLY_7_US_SNAPSHOTS",
            "scope": "captured_snapshots_only_no_historical_promotion",
            "pit_counts": {"PIT-A": 0, "PIT-B_PROSPECTIVE_ONLY": 7, "PIT-C": 0},
            "history_rows_promoted": 0,
            "gate_promotion": False,
            "evidence_matrix_sha256": PROSPECTIVE_EVIDENCE_HASHES["evidence_matrix.json"],
            "candidate_audit_sha256": PROSPECTIVE_EVIDENCE_HASHES["candidate_audit"],
            "raw_manifest_sha256": PROSPECTIVE_EVIDENCE_HASHES["raw_manifest.json"],
        }
        and manifest_package.get("series_full_gates") == SERIES_GATE_STATUS
        and manifest_package.get("full_blockers") == MANIFEST_BLOCKERS
        and all(manifest_package.get(field) is False for field in ("shadow_allowed", "full_history_allowed", "formal_execution_allowed", "formal_curated_written", "research_ready"))
    )
    registry_exact = (
        registry.get("series_count") == 44
        and registry.get("inventory_summary", {}).get("w1_series_total") == 44
        and all(source in registry.get("sources", {}) for source in SOURCES)
        and all(
            registered.get(series_id, {}).get("package") == "global_financial_conditions"
            and registered.get(series_id, {}).get("source") == series_by_id.get(series_id, {}).get("source")
            and registered.get(series_id, {}).get("state") == (
                "FULL_HISTORY_EVIDENCE_ACCEPTED_PIT_C_FORMAL_NOT_AUTHORIZED" if series_id in READY_SERIES
                else "OFFICIAL_PRODUCT_CONFIRMED_ENTITLEMENT_BLOCKED" if series_id == "USD.CNY"
                else "SOURCE_AND_ENTITLEMENT_BLOCKED"
            )
            for series_id in SERIES_ORDER
        )
    )
    checks = {
        "documents_readable": True,
        "package_identity": package.get("contract_id") == "R011.W1.GLOBAL_FINANCIAL_CONDITIONS.V1" and package.get("package_id") == "global_financial_conditions",
        "independent_package_boundary": package.get("independent_from") == ["rates_liquidity"] and not any(series_id.startswith("CN.") for series_id in SERIES_ORDER),
        "decisions_exact": package.get("accepted_decisions") == DECISIONS,
        "sources_exact": package.get("source_whitelist") == SOURCES,
        "layers_exact": package.get("layers") == LAYERS,
        "nine_series_exact": isinstance(series, list) and [item.get("series_id") for item in series if isinstance(item, dict)] == SERIES_ORDER,
        "series_metadata_complete": metadata_exact,
        "windows_exact": window_exact,
        "pit_asof_fail_closed": pit_exact,
        "regime_breaks_exact": package.get("required_regime_breaks") == REGIME_BREAKS,
        "candidate_rules_fail_closed": no_proxy_fill,
        "fx_semantic_boundary": fx_boundary,
        "gold_evidence_frozen_7_of_9": gold_evidence_exact,
        "prospective_pit_b_evidence_frozen": prospective_evidence_exact,
        "seven_series_full_evidence_gates": series_full_evidence_exact,
        "package_states_blocked": fail_closed_states and package.get("status") == "GOLD_BLOCKED_PARTIAL_7_OF_9",
        "manifest_state_exact": manifest_exact,
        "registry_union_exact": registry_exact,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "series_order": SERIES_ORDER,
        "layers": LAYERS,
        "full_history_allowed": package.get("full_history_allowed"),
        "research_ready": package.get("research_ready"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    result = validate_global_financial_conditions_contract(args.package, args.manifest, args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
