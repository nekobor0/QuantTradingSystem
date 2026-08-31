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
DECISIONS = ["GFC_D1", "GFC_D2", "GFC_D3", "GFC_D4"]
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
    "USD.CNY and USD.CNH still require official two-period Gold evidence",
    "all nine series still require complete official full-history evidence",
    "USD.CNH exact official historical source, matched observation time, and entitlement remain unresolved",
    "PIT-A release vintages and required regime breaks have not been captured and validated",
]
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
            "retrospective_history_without_release_evidence",
            "nyfed_initial_publication",
            "nyfed_revision_cutoff",
            "treasury_publication",
            "broad_dollar_publication",
            "usd_cny_publication",
            "usd_cnh_publication",
            "cross_market_alignment",
        )
    ) and pit.get("retrospective_history_without_release_evidence") == "PIT_C_EXPLORATORY_ONLY" and pit.get("nyfed_initial_publication") == {
        "EFFR": "approximately 09:00 America/New_York on the next NYFed business day",
        "SOFR": "approximately 08:00 America/New_York on the next SIFMA business day",
    } and pit.get("nyfed_revision_cutoff") == "approximately 14:30 America/New_York on the publication day; initial and revised observations require distinct immutable vintages"
    fx_boundary = (
        series_by_id.get("USD.CNY", {}).get("official_field") == "USD_CNY_1630_SPOT_CLOSE"
        and series_by_id.get("USD.CNY", {}).get("measure_basis") == "official_interbank_spot_closing_price_1630"
        and series_by_id.get("USD.CNH", {}).get("implementation") == "SOURCE_AND_ENTITLEMENT_BLOCKED"
        and series_by_id.get("USD.CNH", {}).get("license_scope") == "entitlement_unresolved"
    )
    evidence = package.get("gold_candidate_evidence")
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
        and all(
            series_by_id[series_id].get("pit_grade") == "C_GOLD_FROZEN_PENDING_FULL_HISTORY"
            and series_by_id[series_id].get("implementation") == "GOLD_READY_FROZEN_CANDIDATE_PIT_C"
            for series_id in READY_SERIES
        )
    )
    manifest_exact = (
        len(manifest_matches) == 1
        and manifest_package.get("order") == 6
        and manifest_package.get("gold_state") == "GOLD_BLOCKED_PARTIAL_7_OF_9"
        and manifest_package.get("gold_coverage") == {"ready_count": 7, "required_count": 9, "missing_series": MISSING_SERIES}
        and manifest_package.get("shadow_state") == "GOLD_PARTIAL_7_OF_9_NO_PACKAGE_SHADOW"
        and manifest_package.get("contract_id") == "R011.W1.GLOBAL_FINANCIAL_CONDITIONS.V1"
        and manifest_package.get("series_count") == 9
        and manifest_package.get("independent_from") == ["rates_liquidity"]
        and manifest_package.get("layers") == list(LAYERS)
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
                "GOLD_READY_FROZEN_CANDIDATE_PIT_C" if series_id in READY_SERIES
                else "CONTRACT_ONLY" if series_id == "USD.CNY"
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
