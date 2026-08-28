"""Independent validation for the audit-only full-history growth candidate."""

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
from quant_trading_system.research.macro_data.w1_execution import AUDIT_REQUIRED, validate_audit  # noqa: E402
GDP_SERIES = ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY")
INDUSTRIAL_SERIES = ("CN.INDUSTRIAL.VA.YOY",)
GDP_START = "1992-Q1"
GDP_END = "2026-Q2"
INDUSTRIAL_START = "1998-01"
INDUSTRIAL_END = "2026-07"


def _publication(value: Any) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("empty publication time")
    normalized = re.sub(r"年|月", "-", text.replace("日", " ").replace("/", "-")).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"unparseable publication time: {value}")


def _shanghai(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.utcoffset() != timedelta(hours=8):
        raise ValueError("timestamp is not +08:00")
    return parsed


def _months(start: str, end: str) -> list[str]:
    year, month = int(start[:4]), int(start[5:7])
    end_year, end_month = int(end[:4]), int(end[5:7])
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def _quarters(start: str, end: str) -> list[str]:
    year, quarter = int(start[:4]), int(start[-1])
    end_year, end_quarter = int(end[:4]), int(end[-1])
    result: list[str] = []
    while (year, quarter) <= (end_year, end_quarter):
        result.append(f"{year:04d}-Q{quarter}")
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
    return result


def _industrial_structural_omission(period: str) -> bool:
    return int(period[:4]) >= 2005 and period.endswith("-01")


def _expected_periods() -> dict[str, list[str]]:
    return {
        "gdp": _quarters(GDP_START, GDP_END),
        "industrial": [period for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if not _industrial_structural_omission(period)],
    }


def _expected_keys() -> set[str]:
    periods = _expected_periods()
    return {f"{series}|{period}" for period in periods["gdp"] for series in GDP_SERIES} | {f"CN.INDUSTRIAL.VA.YOY|{period}" for period in periods["industrial"]}


def _expected_structural_omissions() -> list[dict[str, str]]:
    return [{"series_id": "CN.INDUSTRIAL.VA.YOY", "period": period, "reason": "January single-month value is not officially published"} for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if _industrial_structural_omission(period)]


def _expected_provisional_periods() -> list[str]:
    return [period for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if 1998 <= int(period[:4]) <= 2004 and period.endswith("-01")]


def _records(audit: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(str(source.get("source_id", "")), item) for source in audit.get("sources", []) for item in source.get("raw_manifests", [])]


def _mismatch(candidate: set[str], observed: set[str], expected: set[str]) -> dict[str, list[str]]:
    return {
        "candidate_only_vs_expected": sorted(candidate - expected),
        "audit_observed_only_vs_expected": sorted(observed - expected),
        "expected_missing_from_candidate": sorted(expected - candidate),
        "expected_missing_from_audit_observed": sorted(expected - observed),
        "candidate_only_vs_audit": sorted(candidate - observed),
        "audit_only_vs_candidate": sorted(observed - candidate),
    }


def validate_full_candidate(candidate_path: Path, audit_path: Path, source_map_path: Path) -> dict[str, Any]:
    expected_period_map = _expected_periods()
    expected = _expected_keys()
    failures: list[str] = []
    try:
        document = json.loads(audit_path.read_text(encoding="utf-8"))
        audit = document["audit"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"passed": False, "failures": [f"audit_readable:{exc}"], "expected_periods_independent_count": len(expected), "series_counts": {}, "manifest_count": 0, "pit_failure_count": 0, "key_set_mismatch": {}}
    try:
        source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
        source_map_keys = set(source_map["expected_keys"])
        if source_map_keys != expected:
            failures.append("source_map_expected_keys")
        scope = source_map.get("scope", {})
        if scope.get("expected_key_count") != len(expected) or scope.get("gdp", {}).get("expected_cells") != 276 or scope.get("industrial", {}).get("expected_cells") != 321:
            failures.append("source_map_scope_counts")
        map_classes = source_map.get("scope", {}).get("industrial_period_classes", {})
        if set(map_classes.get("expected_periods", [])) != set(expected_period_map["industrial"]):
            failures.append("source_map_industrial_expected_periods")
        structural_map = set(map_classes.get("structural_omission_periods", []))
        if structural_map != {item["period"] for item in _expected_structural_omissions()}:
            failures.append("source_map_structural_omissions")
        if set(map_classes.get("provisional_periods_awaiting_official_evidence", [])) != set(_expected_provisional_periods()):
            failures.append("source_map_provisional_periods")
        industrial_map = source_map.get("series", {}).get("CN.INDUSTRIAL.VA.YOY", {})
        if set(industrial_map.get("provisional_periods_awaiting_official_evidence", [])) != set(_expected_provisional_periods()):
            failures.append("series_provisional_periods")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        source_map_keys = set()
        failures.append(f"source_map_readable:{exc}")
    base_audit = {key: audit.get(key) for key in AUDIT_REQUIRED}
    audit_check = validate_audit(base_audit)
    if not audit_check["passed"]:
        failures.extend(f"audit:{item}" for item in audit_check["failures"])
    try:
        frame = pd.read_parquet(candidate_path)
        candidate_readable = True
    except (OSError, ValueError, ImportError) as exc:
        frame = pd.DataFrame()
        candidate_readable = False
        failures.append(f"candidate_readable:{exc}")
    canonical = validate_canonical_v2(frame) if not frame.empty else {"passed": False, "failures": ["empty_frame"]}
    if not canonical["passed"]:
        failures.extend(f"canonical:{item}" for item in canonical["failures"])
    has_columns = list(frame.columns) == CANONICAL_V2_COLUMNS
    candidate_keys = {f"{row.series_id}|{row.reference_period}" for row in frame.itertuples()} if has_columns else set()
    observed = {str(value) for value in audit.get("observed_periods", [])} if isinstance(audit.get("observed_periods"), list) else set()
    audit_expected = {str(value) for value in audit.get("expected_periods", [])} if isinstance(audit.get("expected_periods"), list) else set()
    mismatch = _mismatch(candidate_keys, observed, expected)
    if candidate_keys != observed:
        failures.append("candidate_audit_key_mismatch")
    if audit_expected != expected or len(audit.get("expected_periods", [])) != len(expected):
        failures.append("audit_expected_not_independent")
    if audit.get("requested_window") != {"start": GDP_START, "end": INDUSTRIAL_END}:
        failures.append("requested_window")
    missing = sorted(expected - candidate_keys)
    if sorted(audit.get("unexplained_missing", [])) != missing:
        failures.append("unexplained_missing_not_exact")
    if audit.get("research_ready") is not False:
        failures.append("research_ready_true")
    if missing and audit.get("blocked") is not True:
        failures.append("missing_without_blocker")
    if not missing and audit.get("blocked") is True:
        failures.append("complete_candidate_blocked")
    if audit.get("structural_omissions") != _expected_structural_omissions():
        failures.append("structural_omissions_not_exact")
    series_counts = {series: int((frame["series_id"] == series).sum()) if "series_id" in frame else 0 for series in ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY", "CN.INDUSTRIAL.VA.YOY")}
    duplicate_keys = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if has_columns else 0
    domain_failures = int((~frame["value"].between(-100.0, 2_000_000.0)).sum()) if has_columns else 0
    if duplicate_keys:
        failures.append("duplicate_primary_keys")
    if domain_failures:
        failures.append("value_domain_failures")
    pit_failures: list[str] = []
    if has_columns:
        for index, row in frame.iterrows():
            try:
                release = _shanghai(row["release_at"])
                available = _shanghai(row["available_at"])
                tradable = _shanghai(row["tradable_at"])
                if release != available or release != tradable:
                    raise ValueError("release/available/tradable mismatch")
                if not str(row["availability_evidence"]).strip():
                    raise ValueError("empty availability evidence")
                series = str(row["series_id"])
                period = str(row["reference_period"])
                if series == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-01") and int(period[:4]) >= 2005:
                    raise ValueError("January industrial row")
                if series == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-02"):
                    joint = int(period[:4]) >= 2012
                    expected_span = period[:4] + "-01/02" if joint else period
                    if str(row["reference_period_start"]) != (period[:4] + "-01" if joint else period) or str(row["reference_period_end"]) != period or str(row["period_span"]) != expected_span:
                        raise ValueError("February regime or period span")
                if series == "CN.GDP.NOMINAL.YTD" and (row["unit"] != "100m_cny" or row["measure_basis"] != "ytd_cumulative"):
                    raise ValueError("GDP nominal is not YTD cumulative")
                if row["pit_grade"] not in {"A", "C"}:
                    raise ValueError("full candidate PIT grade is not A/C")
                if row["pit_grade"] == "A" and row["source_id"] != "NBS_RELEASE":
                    raise ValueError("PIT-A source mismatch")
                if row["pit_grade"] == "C" and row["source_id"] != "NBS_DATA":
                    raise ValueError("PIT-C source mismatch")
            except (TypeError, ValueError, OverflowError, KeyError) as exc:
                pit_failures.append(f"row={index}:{exc}")
    else:
        pit_failures.append("candidate missing canonical columns")
    if pit_failures:
        failures.append("pit_failures")
    manifest_failures: list[str] = []
    manifest_shas: set[str] = set()
    release_manifest_count = 0
    pit_a_manifest_count = 0
    pit_c_manifest_count = 0
    for source_id, item in _records(audit):
        path = Path(str(item.get("manifest_path", "")))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            url = str(manifest["request"]["url"])
            status = int(manifest["response"]["status"])
            if not (url.startswith("https://www.stats.gov.cn/") or url.startswith("https://data.stats.gov.cn/")):
                manifest_failures.append(f"{path}:non_official_url")
            if source_id == "NBS_RELEASE":
                release_manifest_count += 1
                pit_a_manifest_count += int(item.get("pit_grade") == "A")
                if status != 200:
                    manifest_failures.append(f"{path}:release_status={status}")
                _publication(manifest["page_publication_time_original"])
            elif source_id == "NBS_DATA":
                pit_c_manifest_count += int(item.get("pit_grade") == "C")
            raw = Path(str(manifest["raw_path"]))
            digest = str(manifest["sha256"])
            manifest_shas.add(digest)
            if not raw.exists() or int(manifest["bytes"]) != raw.stat().st_size or hashlib.sha256(raw.read_bytes()).hexdigest() != digest:
                manifest_failures.append(f"{path}:raw_hash_or_bytes")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            manifest_failures.append(f"{path}:{type(exc).__name__}:{exc}")
    candidate_shas = {str(value) for value in frame["raw_sha256"].dropna()} if "raw_sha256" in frame else set()
    if not candidate_shas.issubset(manifest_shas):
        failures.append("candidate_raw_sha_not_closed")
    if manifest_failures:
        failures.append("manifest_failures")
    if audit.get("raw_hashes_valid") is not True:
        failures.append("audit_raw_hashes_invalid")
    checks = {
        "audit_contract": not any(item.startswith("audit:") for item in failures),
        "candidate_readable": candidate_readable,
        "canonical_v2": bool(canonical["passed"]),
        "source_map_independent": source_map_keys == expected,
        "requested_window_exact": audit.get("requested_window") == {"start": "1992-Q1", "end": "2026-07"},
        "independent_expected_key_count": len(expected) == 597,
        "candidate_audit_key_equality": candidate_keys == observed,
        "audit_expected_exact": audit_expected == expected,
        "missing_accounted": sorted(audit.get("unexplained_missing", [])) == missing,
        "raw_hash_closure": candidate_shas.issubset(manifest_shas),
        "pit_rows_valid": not pit_failures,
        "release_manifests_valid": not manifest_failures,
        "research_ready_false": audit.get("research_ready") is False,
    }
    return {
        "passed": not failures,
        "checks": checks,
        "failures": sorted(set(failures)),
        "rows": int(len(frame)),
        "expected_periods_independent_count": len(expected),
        "observed_cells": len(candidate_keys),
        "series_counts": series_counts,
        "duplicate_primary_keys": duplicate_keys,
        "value_domain_failures": domain_failures,
        "pit_failure_count": len(pit_failures),
        "pit_failure_details": pit_failures,
        "pit_a_manifest_count": pit_a_manifest_count,
        "pit_c_manifest_count": pit_c_manifest_count,
        "manifest_count": len(_records(audit)),
        "release_manifest_count": release_manifest_count,
        "candidate_raw_sha256_distinct_count": len(candidate_shas),
        "manifest_sha256_distinct_count": len(manifest_shas),
        "key_set_mismatch": mismatch,
        "unexplained_missing_count": len(missing),
        "research_ready": False,
        "expected_series_period_counts": {"CN.GDP.NOMINAL.YTD": len(expected_period_map["gdp"]), "CN.GDP.REAL.YOY": len(expected_period_map["gdp"]), "CN.INDUSTRIAL.VA.YOY": len(expected_period_map["industrial"])},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=ROOT / "artifacts" / "macro_r011" / "shadow" / "w1_growth_output_full_range_candidate.parquet")
    parser.add_argument("--audit", type=Path, default=ROOT / "artifacts" / "macro_r011" / "audits" / "w1_growth_output_full_range_audit.json")
    parser.add_argument("--source-map", type=Path, default=ROOT / "artifacts" / "macro_r011" / "state" / "w1_growth_output_luna_full_candidate" / "w1_growth_output_full_range_source_map.json")
    args = parser.parse_args()
    result = validate_full_candidate(args.candidate, args.audit, args.source_map)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
