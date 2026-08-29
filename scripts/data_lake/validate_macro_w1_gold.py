"""Validate ignored local W1 gold evidence without committing market data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "data_lake"))

from validate_macro_w1_rates_gold_candidate import (  # noqa: E402
    EXISTING_READY_SERIES,
    FULL_HISTORY_BLOCKED_SERIES,
    GOLD_MISSING_SERIES,
    NEW_READY_SERIES,
    validate_rates_gold_candidate,
)
from validate_macro_w1_money_credit_afre_candidate import (  # noqa: E402
    FROZEN_HASHES as MONEY_AFRE_FROZEN_HASHES,
    SERIES_ID as MONEY_AFRE_SERIES_ID,
    validate_money_credit_afre_candidate,
)


READY = "GOLD_READY_SHADOW_ONLY"
MONEY_LEGACY_READY_SERIES = {
    "CN.MONEY.M1.BALANCE",
    "CN.MONEY.M2.BALANCE",
    "CN.TSF.FLOW",
    "CN.TSF.STOCK",
    "CN.TSF.GOV_BOND.FLOW",
}
MONEY_READY_SERIES = MONEY_LEGACY_READY_SERIES | {MONEY_AFRE_SERIES_ID}
MONEY_MISSING_SERIES = {
    "CN.LOANS.RMB.FLOW",
    "CN.LOANS.CORP.MEDIUM_LONG.FLOW",
}
MONEY_LEGACY_MISSING_SERIES = MONEY_MISSING_SERIES | {MONEY_AFRE_SERIES_ID}
MONEY_AFRE_POLICY = {
    "series_id": "CN.TSF.RMB_LOANS.FLOW",
    "official_table": "AFRE(flow)",
    "official_field": "RMB loans",
    "semantic_scope": "loans_to_the_real_economy_afre_component",
    "observation_policy": "direct_monthly_official_table_only",
    "not_equivalent_to": ["CN.LOANS.RMB.FLOW"],
    "cumulative_differencing_allowed": False,
    "balance_differencing_allowed": False,
    "methodology_version_required": True,
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_package(package_id: str, spec: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    root = ROOT / spec["fixture_root"]
    expected_series = {item["series_id"] for item in contract["series"]}
    covered = set(spec.get("covered_series", expected_series))
    blocked = set(spec.get("blocked_series", []))
    checks: dict[str, bool] = {
        "coverage_partition_exact": covered | blocked == expected_series and not covered & blocked,
        "two_fixture_periods": len(spec["fixtures"]) == 2,
        "status_matches_coverage": (spec["status"] == READY) == (covered == expected_series),
    }
    if package_id == "money_credit":
        coverage = contract.get("gold_coverage", {})
        afre_series = next((item for item in contract.get("series", []) if item.get("series_id") == MONEY_AFRE_SERIES_ID), {})
        candidate = validate_money_credit_afre_candidate()
        candidate_evidence = spec.get("candidate_evidence", {})
        effective_coverage = spec.get("effective_gold_coverage", {})
        checks.update(
            {
                "money_contract_v3": contract.get("contract_id") == "R011.W1.MONEY_CREDIT.V3",
                "legacy_five_of_eight_partition_exact": covered == MONEY_LEGACY_READY_SERIES
                and blocked == MONEY_LEGACY_MISSING_SERIES,
                "candidate_evidence_valid": candidate["passed"],
                "candidate_evidence_contract_exact": candidate_evidence.get("series_id") == MONEY_AFRE_SERIES_ID
                and candidate_evidence.get("candidate_root") == "artifacts/macro_r011/gold_fixtures/w1_money_credit_candidate_v3"
                and candidate_evidence.get("candidate_audit") == "artifacts/macro_r011/audits/w1_money_credit_afre_gold_candidate_v1.json"
                and candidate_evidence.get("frozen_sha256") == {
                    "expected.json": MONEY_AFRE_FROZEN_HASHES["expected"],
                    "source_map.json": MONEY_AFRE_FROZEN_HASHES["source_map"],
                    "manual_audit.json": MONEY_AFRE_FROZEN_HASHES["manual_audit"],
                    "candidate_audit": MONEY_AFRE_FROZEN_HASHES["candidate_audit"],
                },
                "six_of_eight_effective_coverage_exact": spec.get("status") == "GOLD_BLOCKED_PARTIAL_6_OF_8"
                and contract.get("status") == "GOLD_BLOCKED_PARTIAL_6_OF_8"
                and coverage.get("ready_count") == 6
                and coverage.get("required_count") == 8
                and set(coverage.get("ready_series", [])) == MONEY_READY_SERIES
                and set(coverage.get("missing_series", [])) == MONEY_MISSING_SERIES
                and effective_coverage.get("ready_count") == 6
                and effective_coverage.get("required_count") == 8
                and set(effective_coverage.get("ready_series", [])) == MONEY_READY_SERIES
                and set(effective_coverage.get("missing_series", [])) == MONEY_MISSING_SERIES,
                "afre_semantic_policy_exact": contract.get("afre_rmb_loans_policy") == MONEY_AFRE_POLICY,
                "afre_series_gold_state_exact": afre_series.get("measure_basis") == "direct_afre_component_flow"
                and afre_series.get("implementation") == "GOLD_READY_FROZEN_CANDIDATE",
                "money_formal_states_false": contract.get("full_history_allowed") is False
                and contract.get("formal_curated_written") is False
                and contract.get("research_ready") is False,
            }
        )
    periods: dict[str, Any] = {}
    required = set(spec.get("required_files", []))
    for fixture_id in spec["fixtures"]:
        period_root = root / fixture_id
        present = all((period_root / name).is_file() for name in required)
        period_checks: dict[str, bool] = {"required_files_present": present}
        if present:
            expected = _load(period_root / "expected.json")
            checksums = _load(period_root / "checksums.json")["files"]
            rows = expected["rows"]
            row_series = {row["series_id"] for row in rows}
            period_checks.update(
                {
                    "fixture_id_matches": expected["fixture_id"] == fixture_id,
                    "covered_series_exact": row_series == covered,
                    "unique_series": len(rows) == len(row_series),
                    "finite_numeric_values": all(isinstance(row["value"], (int, float)) for row in rows),
                    "source_files_present": all((period_root / row["source_file"]).is_file() for row in rows),
                    "checksums_complete": set(checksums) == {name for name in required if name not in {"expected.json", "checksums.json"}},
                    "raw_checksums_match": all((period_root / name).is_file() and _sha256(period_root / name) == digest for name, digest in checksums.items()),
                    "omissions_match_blocked": {item["series_id"] for item in expected.get("expected_omissions", [])}
                    == (blocked - {"CN.TSF.RMB_LOANS.FLOW"} if package_id == "money_credit" else blocked),
                }
            )
        periods[fixture_id] = period_checks
    failures = sorted(
        [name for name, passed in checks.items() if not passed]
        + [f"{period}:{name}" for period, values in periods.items() for name, passed in values.items() if not passed]
    )
    return {
        "package_id": package_id,
        "evidence_valid": not failures,
        "package_ready": not failures and spec["status"] == READY,
        "status": spec["status"],
        **(
            {
                "gold_ready_count": 6,
                "gold_required_count": 8,
                "gold_missing": sorted(MONEY_MISSING_SERIES),
                "candidate": candidate,
            }
            if package_id == "money_credit"
            else {}
        ),
        "checks": checks,
        "periods": periods,
        "failures": failures,
    }


def validate_registry(registry_path: Path) -> dict[str, Any]:
    registry = _load(registry_path)
    results: dict[str, Any] = {}
    for package_id, spec in registry["packages"].items():
        contract = _load(ROOT / "config" / "macro_w1_packages" / f"{package_id}.json")
        if package_id == "rates_liquidity":
            expected_series = {item["series_id"] for item in contract["series"]}
            covered = set(spec["covered_series"])
            blocked = set(spec["blocked_series"])
            candidate = validate_rates_gold_candidate()
            coverage = contract.get("gold_coverage", {})
            coverage_exact = (
                coverage.get("ready_count") == 9
                and coverage.get("required_count") == 11
                and set(coverage.get("ready_series", [])) == EXISTING_READY_SERIES | NEW_READY_SERIES
                and set(coverage.get("missing_series", [])) == GOLD_MISSING_SERIES
                and set(contract.get("full_history_blocked_series", [])) == FULL_HISTORY_BLOCKED_SERIES
            )
            registry_partition_exact = (
                covered == EXISTING_READY_SERIES
                and blocked == expected_series - EXISTING_READY_SERIES
                and covered | blocked == expected_series
                and not covered & blocked
            )
            checks = {
                "legacy_gold_partition_exact": registry_partition_exact,
                "candidate_evidence_valid": candidate["passed"],
                "nine_of_eleven_coverage_exact": coverage_exact,
                "package_remains_blocked": contract.get("status") == "GOLD_BLOCKED_PARTIAL_9_OF_11",
                "formal_and_research_states_false": contract.get("full_history_allowed") is False and contract.get("formal_curated_written") is False and contract.get("research_ready") is False,
            }
            failures = sorted(name for name, passed in checks.items() if not passed)
            results[package_id] = {
                "package_id": package_id,
                "evidence_valid": not failures,
                "package_ready": False,
                "status": contract.get("status"),
                "gold_ready_count": candidate["gold_ready_count"],
                "gold_required_count": candidate["gold_required_count"],
                "gold_missing": candidate["gold_missing"],
                "full_history_blocked_series": candidate["full_history_blocked_series"],
                "checks": checks,
                "periods": {},
                "candidate": candidate,
                "failures": failures,
            }
        else:
            results[package_id] = validate_package(package_id, spec, contract)
    invalid = sorted(key for key, value in results.items() if not value["evidence_valid"])
    return {
        "passed": not invalid,
        "ready_packages": sorted(key for key, value in results.items() if value["package_ready"]),
        "blocked_packages": sorted(key for key, value in results.items() if not value["package_ready"]),
        "invalid_packages": invalid,
        "packages": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=ROOT / "config" / "macro_w1_gold_registry.json")
    args = parser.parse_args()
    result = validate_registry(args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
