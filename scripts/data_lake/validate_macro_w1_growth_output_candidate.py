"""Independent validator for the bounded official growth-output candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import CANONICAL_V2_COLUMNS, validate_canonical_v2  # noqa: E402
from quant_trading_system.research.macro_data.w1_execution import validate_audit  # noqa: E402


MANIFEST_REQUIRED = {"source_id", "retrieved_at", "sha256", "bytes", "raw_path", "request", "response", "discovery_mechanism", "page_publication_time_original"}
GDP_PERIODS = ("2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2")
INDUSTRIAL_PERIODS = ("2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07")
GDP_SERIES = ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY")
EXPECTED_WINDOW = {"start": "2024-08", "end": "2026-07"}


def _expected_keys() -> set[str]:
    return {f"{series}|{period}" for period in GDP_PERIODS for series in GDP_SERIES} | {f"CN.INDUSTRIAL.VA.YOY|{period}" for period in INDUSTRIAL_PERIODS}


def _parse_publication(value: Any) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("empty page_publication_time_original")
    normalized = re.sub(r"年|月", "-", text.replace("日", " ").replace("/", "-")).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"unparseable publication time: {value}")


def _parse_shanghai(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.utcoffset() != timedelta(hours=8):
        raise ValueError(f"timestamp is not +08:00: {value}")
    return parsed


def _key_set_mismatch(candidate: set[str], audit_observed: set[str], expected: set[str]) -> dict[str, Any]:
    return {
        "candidate_only": sorted(candidate - expected),
        "audit_observed_only": sorted(audit_observed - expected),
        "expected_only_in_candidate": sorted(expected - candidate),
        "expected_only_in_audit_observed": sorted(expected - audit_observed),
        "candidate_vs_audit": {"candidate_only": sorted(candidate - audit_observed), "audit_observed_only": sorted(audit_observed - candidate)},
    }


def validate_candidate(candidate_path: Path, audit_path: Path) -> dict[str, Any]:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    independent_expected = _expected_keys()
    try:
        document = json.loads(audit_path.read_text(encoding="utf-8"))
        audit = document["audit"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "passed": False, "checks": {"audit_readable": False}, "failures": [f"audit_readable:{exc}"],
            "series_counts": {}, "manifest_count": 0, "key_set_mismatch": {}, "pit_failure_count": 0,
            "expected_periods_independent_count": len(independent_expected), "research_ready": False,
        }
    audit_validation = validate_audit(audit)
    checks["audit_contract"] = bool(audit_validation["passed"])
    if not checks["audit_contract"]:
        failures.extend(f"audit:{item}" for item in audit_validation["failures"])

    try:
        frame = pd.read_parquet(candidate_path)
        checks["candidate_readable"] = True
    except (OSError, ValueError, ImportError) as exc:
        checks["candidate_readable"] = False
        failures.append(f"candidate_readable:{exc}")
        frame = pd.DataFrame()
    canonical = validate_canonical_v2(frame) if not frame.empty else {"passed": False, "failures": ["empty_frame"]}
    checks["canonical_v2"] = bool(canonical["passed"])
    if not checks["canonical_v2"]:
        failures.extend(f"canonical:{item}" for item in canonical["failures"])

    has_candidate_columns = set(CANONICAL_V2_COLUMNS).issubset(frame.columns)
    candidate_keys = {f"{row.series_id}|{row.reference_period}" for row in frame.itertuples()} if has_candidate_columns else set()
    audit_observed = {str(value) for value in audit.get("observed_periods", [])} if isinstance(audit.get("observed_periods"), list) else set()
    audit_expected = {str(value) for value in audit.get("expected_periods", [])} if isinstance(audit.get("expected_periods"), list) else set()
    mismatch = _key_set_mismatch(candidate_keys, audit_observed, independent_expected)
    checks["requested_window_exact"] = audit.get("requested_window") == EXPECTED_WINDOW
    checks["expected_periods_independent_exact"] = audit_expected == independent_expected and len(audit_expected) == 38
    checks["candidate_audit_independent_keys_equal"] = candidate_keys == audit_observed == independent_expected
    if not checks["requested_window_exact"]:
        failures.append("requested_window")
    if not checks["expected_periods_independent_exact"]:
        failures.append("expected_periods_independent")
    if not checks["candidate_audit_independent_keys_equal"]:
        failures.append("key_set_mismatch")

    series_counts = {series: int((frame["series_id"] == series).sum()) if "series_id" in frame else 0 for series in (*GDP_SERIES, "CN.INDUSTRIAL.VA.YOY")}
    checks["row_count_exact_38"] = len(frame) == 38
    checks["series_counts_exact"] = series_counts == {"CN.GDP.NOMINAL.YTD": 8, "CN.GDP.REAL.YOY": 8, "CN.INDUSTRIAL.VA.YOY": 22}
    if not checks["row_count_exact_38"]:
        failures.append("row_count_not_38")
    if not checks["series_counts_exact"]:
        failures.append("series_counts")

    checks["audit_unblocked"] = audit.get("blocked") is False and audit.get("blockers") == []
    checks["audit_missingness_empty"] = audit.get("unexplained_missing") == [] and audit.get("structural_omissions") == []
    checks["audit_raw_hashes_valid"] = audit.get("raw_hashes_valid") is True
    for check, failure in (("audit_unblocked", "audit_blocked"), ("audit_missingness_empty", "audit_missingness"), ("audit_raw_hashes_valid", "audit_raw_hashes_invalid")):
        if not checks[check]:
            failures.append(failure)

    duplicate_keys = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if has_candidate_columns else 0
    checks["duplicate_primary_keys_zero"] = duplicate_keys == 0
    if duplicate_keys:
        failures.append("duplicate_primary_keys")
    checks["research_ready_false"] = audit.get("research_ready") is False
    if not checks["research_ready_false"]:
        failures.append("research_ready_true")

    raw_sha_values = {str(value) for value in frame["raw_sha256"].dropna()} if "raw_sha256" in frame else set()
    manifests = audit.get("sources", [{}])[0].get("raw_manifests", []) if audit.get("sources") else []
    manifest_failures: list[str] = []
    manifest_shas: set[str] = set()
    for item in manifests:
        path = Path(str(item.get("manifest_path", "")))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            missing = MANIFEST_REQUIRED - set(manifest)
            if missing:
                manifest_failures.append(f"{path}:missing={sorted(missing)}")
                continue
            url = str(manifest["request"].get("url", "")) if isinstance(manifest["request"], dict) else ""
            status = manifest["response"].get("status") if isinstance(manifest["response"], dict) else None
            if not url.startswith("https://www.stats.gov.cn/"):
                manifest_failures.append(f"{path}:non_official_url")
            if status != 200:
                manifest_failures.append(f"{path}:status={status}")
            raw = Path(str(manifest["raw_path"]))
            digest = str(manifest["sha256"])
            manifest_shas.add(digest)
            if int(manifest["bytes"]) != raw.stat().st_size or hashlib.sha256(raw.read_bytes()).hexdigest() != digest:
                manifest_failures.append(f"{path}:raw_hash_or_bytes")
            if not isinstance(manifest["request"], dict) or not manifest["request"].get("method"):
                manifest_failures.append(f"{path}:request")
            _parse_publication(manifest["page_publication_time_original"])
            datetime.fromisoformat(str(manifest["retrieved_at"]).replace("Z", "+00:00"))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            manifest_failures.append(f"{path}:{type(exc).__name__}:{exc}")
    checks["manifest_count_exact_30"] = len(manifests) == 30
    checks["candidate_raw_sha_manifest_set_exact"] = len(raw_sha_values) == 30 and raw_sha_values == manifest_shas and len(manifest_shas) == 30
    checks["raw_manifests_valid"] = not manifest_failures and len(manifests) == 30
    if not checks["manifest_count_exact_30"]:
        failures.append("manifest_count_not_30")
    if not checks["candidate_raw_sha_manifest_set_exact"]:
        failures.append("candidate_raw_sha_manifest_set")
    if not checks["raw_manifests_valid"]:
        failures.extend(f"manifest:{item}" for item in manifest_failures)

    pit_failures: list[str] = []
    if has_candidate_columns:
        for index, row in frame.iterrows():
            try:
                release = _parse_shanghai(row["release_at"])
                available = _parse_shanghai(row["available_at"])
                tradable = _parse_shanghai(row["tradable_at"])
                if release != available or release != tradable:
                    raise ValueError("release/available/tradable mismatch")
                evidence = str(row["availability_evidence"]).strip()
                if not evidence or evidence.lower() == "nan":
                    raise ValueError("empty availability_evidence")
            except (TypeError, ValueError, OverflowError) as exc:
                pit_failures.append(f"row={index}:{exc}")
    else:
        pit_failures.append("candidate_missing_canonical_columns")
    checks["pit_rows_valid"] = not pit_failures
    if pit_failures:
        failures.append("pit_rows")

    checks["timestamps_shanghai"] = checks["pit_rows_valid"]
    checks["no_january_synthetic"] = not bool(((frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & frame["reference_period"].astype(str).str.endswith("-01")).any()) if has_candidate_columns else False
    if not checks["no_january_synthetic"]:
        failures.append("january_industrial_row")
    if has_candidate_columns:
        joint = frame[(frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & frame["reference_period"].astype(str).str.endswith("-02")]
        checks["joint_period_span"] = bool(joint.empty or joint["period_span"].astype(str).eq(joint["reference_period"].astype(str).str[:4] + "-01/02").all())
        nominal = frame[frame["series_id"] == "CN.GDP.NOMINAL.YTD"]
        checks["gdp_nominal_ytd_basis"] = bool(nominal.empty or (nominal["measure_basis"].eq("ytd_cumulative") & nominal["unit"].eq("100m_cny")).all())
    else:
        checks["joint_period_span"] = False
        checks["gdp_nominal_ytd_basis"] = False
    if not checks["joint_period_span"]:
        failures.append("joint_period_span")
    if not checks["gdp_nominal_ytd_basis"]:
        failures.append("gdp_nominal_not_ytd")

    return {
        "passed": not failures,
        "checks": checks,
        "failures": sorted(set(failures)),
        "rows": int(len(frame)),
        "expected_cells": len(independent_expected),
        "observed_cells": len(candidate_keys),
        "series_counts": series_counts,
        "manifest_count": len(manifests),
        "candidate_raw_sha256_distinct_count": len(raw_sha_values),
        "manifest_sha256_distinct_count": len(manifest_shas),
        "key_set_mismatch": mismatch,
        "pit_failure_count": len(pit_failures),
        "expected_periods_independent_count": len(independent_expected),
        "research_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=ROOT / "artifacts" / "macro_r011" / "shadow" / "w1_growth_output_bounded_candidate.parquet")
    parser.add_argument("--audit", type=Path, default=ROOT / "artifacts" / "macro_r011" / "audits" / "w1_growth_output_bounded_candidate.json")
    args = parser.parse_args()
    result = validate_candidate(args.candidate, args.audit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
