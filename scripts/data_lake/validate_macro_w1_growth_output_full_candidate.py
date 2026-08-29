"""Independent validation for the audit-only full-history growth candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import CANONICAL_V2_COLUMNS, validate_canonical_v2  # noqa: E402
from quant_trading_system.research.macro_data.w1_execution import AUDIT_REQUIRED, validate_audit  # noqa: E402
from quant_trading_system.research.macro_data.w1_nbs_manual_exports import _parse_gdp, _parse_industrial  # noqa: E402
GDP_SERIES = ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY")
INDUSTRIAL_SERIES = ("CN.INDUSTRIAL.VA.YOY",)
GDP_START = "1992-Q1"
GDP_REAL_START = "1993-Q1"
GDP_END = "2026-Q2"
INDUSTRIAL_START = "1998-07"
INDUSTRIAL_END = "2026-07"
EXPECTED_TOTAL = 581
OFFICIAL_HOSTS = {"www.stats.gov.cn", "stats.gov.cn", "data.stats.gov.cn"}
MANUAL_FREEZE = "2026-08-29T11:50:00+08:00"
EXPECTED_STRUCTURAL_COUNT = 28
MANUAL_SOURCE_ID = "NBS_DATA"
PROFILE_WORKBOOKS = {
    "nbs-GDP-nonchange-price-history-original.xlsx": ("nonchange_profile", "77BE7EA5321446EEC94A4C9E5BB271BBF52C32E128B8DB04B103CD7BBAB92259"),
    "nbs-money-supply-monthly-history-original.xlsx": ("money_profile", "F9198DB9CC5B51BB595BB2EF07DEBA4F7BD39C85DC7B8343942FD7301C9C4AB1"),
    "nbs-government-revenue-history-original.xlsx": ("fiscal_revenue_profile", "7552DBC16BA0570A8E45443E911649EF46A295161BDACD577F100E8CCEDD1583"),
    "nbs-government-spending-history-original.xlsx": ("fiscal_spending_profile", "94CE8EF545E06649740A67AD2B3BD6C33A742277110B8F2CB65EE33BEC12C5B8"),
}


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
    return int(period[:4]) >= 1999 and period.endswith("-01")


def _expected_periods() -> dict[str, list[str]]:
    return {
        "gdp": _quarters(GDP_START, GDP_END),
        "gdp_real": _quarters(GDP_REAL_START, GDP_END),
        "industrial": [period for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if not _industrial_structural_omission(period)],
    }


def _expected_keys() -> set[str]:
    periods = _expected_periods()
    return {f"CN.GDP.NOMINAL.YTD|{period}" for period in periods["gdp"]} | {f"CN.GDP.REAL.YOY|{period}" for period in periods["gdp_real"]} | {f"CN.INDUSTRIAL.VA.YOY|{period}" for period in periods["industrial"]}


def _expected_structural_omissions() -> list[dict[str, str]]:
    return [{"series_id": "CN.INDUSTRIAL.VA.YOY", "period": period, "reason": "January single-month value is not officially published"} for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if _industrial_structural_omission(period)]


def _expected_provisional_periods() -> list[str]:
    return []


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


def _xlsx_clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    return text[1:] if text.startswith("'") else text


def _xlsx_period(value: Any) -> str | None:
    text = _xlsx_clean(value)
    quarter = re.search(r"(\d{4})年第?([一二三四1234])季度", text)
    if quarter:
        number = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(quarter.group(2), quarter.group(2))
        return f"{quarter.group(1)}-Q{number}"
    month = re.search(r"(\d{4})年(\d{1,2})月", text)
    if month:
        return f"{month.group(1)}-{int(month.group(2)):02d}"
    return None


def _xlsx_headers(frame: pd.DataFrame) -> dict[str, int]:
    result: dict[str, int] = {}
    for column in range(1, frame.shape[1]):
        period = _xlsx_period(frame.iat[2, column])
        if period is not None:
            if period in result:
                raise ValueError(f"duplicate XLSX period: {period}")
            result[period] = column
    if not result:
        raise ValueError("profile XLSX has no period headers")
    return result


def _xlsx_row(frame: pd.DataFrame, columns: dict[str, int], row_index: int, label: str) -> dict[str, Any]:
    observed_periods = sorted(period for period, column in columns.items() if _xlsx_clean(frame.iat[row_index, column]))
    return {
        "row_index": row_index,
        "label": label,
        "observed": len(observed_periods),
        "missing": len(columns) - len(observed_periods),
        "earliest_observed": observed_periods[0] if observed_periods else None,
        "latest_observed": observed_periods[-1] if observed_periods else None,
        "observed_periods": observed_periods,
    }


def _xlsx_find_row(frame: pd.DataFrame, required: tuple[str, ...], forbidden: tuple[str, ...] = ()) -> tuple[int, str]:
    matches = []
    for index in range(frame.shape[0]):
        label = _xlsx_clean(frame.iat[index, 0])
        if all(term in label for term in required) and not any(term in label for term in forbidden):
            matches.append((index, label))
    if len(matches) != 1:
        raise ValueError(f"expected one profile XLSX row for {required}, found {len(matches)}")
    return matches[0]


def _profile_from_xlsx(path: Path, kind: str) -> dict[str, Any]:
    frame = pd.read_excel(path, header=None)
    columns = _xlsx_headers(frame)
    periods = sorted(columns)
    result: dict[str, Any] = {
        "file": path.name,
        "kind": kind,
        "header_periods": len(periods),
        "period_count": len(periods),
        "header_earliest": periods[0],
        "header_latest": periods[-1],
        "canonical_rows_added": 0,
    }
    if kind == "nonchange_profile":
        row_index, label = _xlsx_find_row(frame, ("国内生产总值", "不变价", "当季值"), ("累计值",))
        row = _xlsx_row(frame, columns, row_index, label)
        note = next((_xlsx_clean(frame.iat[index, 0]) for index in range(frame.shape[0]) if "基期" in _xlsx_clean(frame.iat[index, 0])), "")
        result.update({
            "observed": row["observed"],
            "missing": row["missing"],
            "earliest": row["earliest_observed"],
            "latest": row["latest_observed"],
            "earliest_observed": row["earliest_observed"],
            "latest_observed": row["latest_observed"],
            "observed_periods": row["observed_periods"],
            "row": row,
            "quarter_count_2007_q1_to_2026_q2": row["observed"],
            "base_period_note": note,
            "cross_base_yoy": False,
        })
    elif kind == "money_profile":
        rows: dict[str, dict[str, Any]] = {}
        for index in range(frame.shape[0]):
            label = _xlsx_clean(frame.iat[index, 0])
            aggregate = next((name for name in ("M0", "M1", "M2") if name in label), None)
            if aggregate is None:
                continue
            measure = "balance" if "期末值" in label else "yoy" if "同比" in label and "增长" in label else None
            if measure is not None:
                rows[f"{aggregate}_{measure}"] = _xlsx_row(frame, columns, index, label)
        expected_rows = {f"{aggregate}_{measure}" for aggregate in ("M0", "M1", "M2") for measure in ("balance", "yoy")}
        if set(rows) != expected_rows:
            raise ValueError(f"money profile rows are incomplete: {sorted(rows)}")
        result.update({
            "m0_m1_m2_field_count": {name: sum(key.startswith(f"{name}_") for key in rows) for name in ("M0", "M1", "M2")},
            "balance_and_yoy_rows_profiled": len(rows),
            "row_profiles": {key: rows[key] for key in sorted(rows)},
            "source_note": "NBS redistribution / underlying PBOC",
            "underlying_source": "PBOC / NBS redistribution",
        })
    else:
        value_index, value_label = _xlsx_find_row(frame, ("累计值",))
        growth_index, growth_label = _xlsx_find_row(frame, ("累计增长",)) if any("累计增长" in _xlsx_clean(frame.iat[index, 0]) for index in range(frame.shape[0])) else _xlsx_find_row(frame, ("累计同比",))
        rows = {
            "cumulative_value": _xlsx_row(frame, columns, value_index, value_label),
            "cumulative_growth": _xlsx_row(frame, columns, growth_index, growth_label),
        }
        result.update({
            "cumulative_value_or_yoy_row_count": len(rows),
            "row_profiles": rows,
            "cumulative_value_observed": rows["cumulative_value"]["observed"],
            "cumulative_value_missing": rows["cumulative_value"]["missing"],
            "cumulative_growth_observed": rows["cumulative_growth"]["observed"],
            "cumulative_growth_missing": rows["cumulative_growth"]["missing"],
            "missing_cells": sum(profile["missing"] for profile in rows.values()),
            "monthly_differencing": False,
        })
    return result


def _overlap_category(series: str, unit_a: str, unit_c: str, difference: float) -> str:
    if difference <= 1e-9:
        return "exact"
    if series == "CN.GDP.NOMINAL.YTD" and unit_a == unit_c == "100m_cny" and difference <= 0.5:
        return "rounding"
    if unit_a == unit_c == "percent_yoy" and difference <= 0.05:
        return "rounding"
    return "revision"


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
        if scope.get("expected_key_count") != EXPECTED_TOTAL or scope.get("gdp", {}).get("expected_cells") != 272 or scope.get("industrial", {}).get("expected_cells") != 309:
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
                if series == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-01"):
                    raise ValueError("January industrial row")
                if series == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-02"):
                    joint = int(period[:4]) >= 2013
                    expected_span = period[:4] + "-01/02" if joint else period
                    if str(row["reference_period_start"]) != (period[:4] + "-01" if joint else period) or str(row["reference_period_end"]) != period or str(row["period_span"]) != expected_span:
                        raise ValueError("February regime or period span")
                if series == "CN.GDP.NOMINAL.YTD" and (row["unit"] != "100m_cny" or row["measure_basis"] != "ytd_cumulative"):
                    raise ValueError("GDP nominal is not YTD cumulative")
                if series == "CN.GDP.REAL.YOY" and row["measure_basis"] != "period_observation":
                    raise ValueError("GDP real is not quarterly index-derived observation")
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
    manual_values: dict[tuple[str, str], float] = {}
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
        "independent_expected_key_count": len(expected) == EXPECTED_TOTAL,
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
        "expected_series_period_counts": {"CN.GDP.NOMINAL.YTD": len(expected_period_map["gdp"]), "CN.GDP.REAL.YOY": len(expected_period_map["gdp_real"]), "CN.INDUSTRIAL.VA.YOY": len(expected_period_map["industrial"])},
    }


def validate_manual_candidate(candidate_path: Path, audit_path: Path, source_map_path: Path | None = None) -> dict[str, Any]:
    """Independently validate the offline manual-export PIT-layered candidate."""
    expected_period_map = _expected_periods()
    expected = _expected_keys()
    failures: list[str] = []
    source_map_keys: set[str] = set()
    if source_map_path is not None:
        try:
            source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
            source_map_keys = {str(item) for item in source_map["expected_keys"]}
            scope = source_map["scope"]
            classes = scope["industrial_period_classes"]
            if source_map_keys != expected:
                failures.append("source_map_expected_keys")
            if scope.get("expected_key_count") != EXPECTED_TOTAL or scope.get("gdp", {}).get("expected_cells") != 272 or scope.get("industrial", {}).get("expected_cells") != 309:
                failures.append("source_map_scope_counts")
            if set(classes.get("expected_periods", [])) != set(expected_period_map["industrial"]):
                failures.append("source_map_industrial_periods")
            if set(classes.get("structural_omission_periods", [])) != {item["period"] for item in _expected_structural_omissions()}:
                failures.append("source_map_structural_omissions")
            if classes.get("provisional_periods_awaiting_official_evidence", []) != []:
                failures.append("source_map_provisional_periods")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append(f"source_map_readable:{exc}")
    try:
        document = json.loads(audit_path.read_text(encoding="utf-8"))
        audit = document["audit"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"passed": False, "failures": [f"audit_readable:{exc}"], "expected_periods_independent_count": len(expected), "series_counts": {}, "manifest_count": 0, "pit_failure_count": 0, "key_set_mismatch": {}}
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
    observed = {str(item) for item in audit.get("observed_periods", [])} if isinstance(audit.get("observed_periods"), list) else set()
    audit_expected = {str(item) for item in audit.get("expected_periods", [])} if isinstance(audit.get("expected_periods"), list) else set()
    mismatch = _mismatch(candidate_keys, observed, expected)
    if candidate_keys != expected:
        failures.append("candidate_expected_key_mismatch")
    if observed != expected:
        failures.append("audit_observed_expected_key_mismatch")
    if audit_expected != expected:
        failures.append("audit_expected_not_independent")
    if audit.get("requested_window") != {"start": GDP_START, "end": INDUSTRIAL_END}:
        failures.append("requested_window")
    if audit.get("unexplained_missing") != []:
        failures.append("unexplained_missing")
    if audit.get("blocked") is not False or audit.get("blockers") != []:
        failures.append("blocked_semantics")
    if audit.get("research_ready") is not False:
        failures.append("research_ready_true")
    expected_structural = _expected_structural_omissions()
    if audit.get("structural_omissions") != expected_structural or len(expected_structural) != EXPECTED_STRUCTURAL_COUNT:
        failures.append("structural_omissions")
    route = document.get("manual_route", {})
    if route.get("status") != "READY" or route.get("mechanism_ready") is not False or route.get("evidence_integrity_passed") is not True or route.get("formal_curated_written") is not False or route.get("freeze") != MANUAL_FREEZE:
        failures.append("manual_route_governance")
    expected_scope_exclusions = {f"CN.GDP.REAL.YOY|{period}" for period in _quarters(GDP_START, "1992-Q4")}
    actual_scope_exclusions = {f"{item.get('series_id')}|{item.get('period')}" for item in route.get("source_scope_exclusions", [])} if isinstance(route.get("source_scope_exclusions"), list) else set()
    if actual_scope_exclusions != expected_scope_exclusions:
        failures.append("gdp_real_scope_exclusions")
    series_counts = {series: int((frame["series_id"] == series).sum()) if "series_id" in frame else 0 for series in ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY", "CN.INDUSTRIAL.VA.YOY")}
    if series_counts != {"CN.GDP.NOMINAL.YTD": 138, "CN.GDP.REAL.YOY": 134, "CN.INDUSTRIAL.VA.YOY": 309}:
        failures.append("series_counts")
    duplicate_keys = int(frame.duplicated(["series_id", "reference_period"]).sum()) if has_columns else 0
    domain_failures = int((~frame["value"].apply(lambda value: isinstance(value, (int, float)) and math.isfinite(float(value))).astype(bool)).sum()) if has_columns else 0
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
                if release != available or release != tradable or not str(row["availability_evidence"]).strip():
                    raise ValueError("PIT timestamps/evidence")
                series, period = str(row["series_id"]), str(row["reference_period"])
                if series == "CN.INDUSTRIAL.VA.YOY":
                    if period.endswith("-01"):
                        raise ValueError("January industrial row")
                    if period.endswith("-02"):
                        joint = int(period[:4]) >= 2013
                        expected_start = f"{period[:4]}-01" if joint else period
                        expected_span = f"{period[:4]}-01/02" if joint else period
                        if str(row["reference_period_start"]) != expected_start or str(row["reference_period_end"]) != period or str(row["period_span"]) != expected_span:
                            raise ValueError("industrial February regime")
                if series == "CN.GDP.NOMINAL.YTD" and (row["unit"] != "100m_cny" or row["measure_basis"] != "ytd_cumulative"):
                    raise ValueError("nominal GDP basis")
                if series == "CN.GDP.REAL.YOY" and (row["unit"] != "percent_yoy" or row["measure_basis"] != "period_observation" or period < GDP_REAL_START):
                    raise ValueError("real GDP index basis or scope")
                if str(row["pit_grade"]) == "A" and str(row["source_id"]) != "NBS_RELEASE":
                    raise ValueError("PIT-A source")
                if str(row["pit_grade"]) == "C":
                    if str(row["source_id"]) != "NBS_DATA" or str(row["release_at"]) != MANUAL_FREEZE or str(row["available_at"]) != MANUAL_FREEZE or str(row["tradable_at"]) != MANUAL_FREEZE or str(row["retrieved_at"]) != MANUAL_FREEZE:
                        raise ValueError("PIT-C freeze/source")
                if str(row["pit_grade"]) not in {"A", "C"}:
                    raise ValueError("PIT grade")
            except (TypeError, ValueError, OverflowError, KeyError) as exc:
                pit_failures.append(f"row={index}:{exc}")
    else:
        pit_failures.append("candidate missing canonical columns")
    if pit_failures:
        failures.append("pit_failures")
    manifest_failures: list[str] = []
    manifest_shas: set[str] = set()
    manual_values: dict[tuple[str, str], float] = {}
    manual_units: dict[tuple[str, str], str] = {}
    manual_drop: Path | None = None
    for source_id, item in _records(audit):
        path = Path(str(item.get("manifest_path", "")))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            raw = Path(str(manifest["raw_path"]))
            digest = str(manifest["sha256"]).upper()
            manifest_shas.add(digest)
            if int(manifest["bytes"]) != raw.stat().st_size or hashlib.sha256(raw.read_bytes()).hexdigest().upper() != digest:
                raise ValueError("raw hash/bytes")
            url = str(manifest["request"]["url"])
            if not (url.startswith("https://www.stats.gov.cn/") or url.startswith("https://data.stats.gov.cn/")):
                raise ValueError("non-official manifest URL")
            if int(manifest["response"]["status"]) != 200:
                raise ValueError("manifest status")
            if source_id == "NBS_RELEASE":
                _publication(manifest["page_publication_time_original"])
            elif source_id == MANUAL_SOURCE_ID:
                if manifest.get("request", {}).get("method") != "LOCAL_MANUAL_EXPORT" or manifest.get("page_publication_time_original") is not None:
                    raise ValueError("manual manifest PIT-C metadata")
                kind = str(manifest["kind"])
                if kind == "gdp_nominal":
                    parsed = _parse_gdp(raw, manifest, "gdp_nominal")
                elif kind == "gdp_real":
                    parsed = _parse_gdp(raw, manifest, "gdp_real")
                elif kind == "industrial":
                    parsed = _parse_industrial(raw, manifest)
                else:
                    raise ValueError("manual manifest is not a canonical workbook")
                for parsed_row in parsed:
                    key = (str(parsed_row["series_id"]), str(parsed_row["reference_period"]))
                    manual_values[key] = float(parsed_row["value"])
                    manual_units[key] = str(parsed_row["unit"])
                manual_drop = raw.parent
            else:
                raise ValueError("unexpected audit source")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            manifest_failures.append(f"{path}:{exc}")
    if has_columns:
        for index, row in frame[frame["pit_grade"].eq("C")].iterrows():
            key = (str(row["series_id"]), str(row["reference_period"]))
            expected_value = manual_values.get(key)
            if expected_value is None or abs(float(row["value"]) - expected_value) > 1e-9:
                pit_failures.append(f"row={index}:manual value does not match frozen XLSX source")
    if pit_failures:
        failures.append("pit_failures")

    profile_failures: list[str] = []
    actual_profiles = route.get("profiles") if isinstance(route.get("profiles"), dict) else {}
    if manual_drop is None:
        profile_failures.append("manual profile workbook directory is unavailable")
    for filename, (kind, expected_sha) in PROFILE_WORKBOOKS.items():
        path = manual_drop / filename if manual_drop is not None else Path(filename)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if digest != expected_sha:
                raise ValueError(f"profile workbook SHA mismatch: {digest}")
            expected_profile = _profile_from_xlsx(path, kind)
            if actual_profiles.get(filename) != expected_profile:
                profile_failures.append(f"profile mismatch: {filename}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            profile_failures.append(f"{filename}:{exc}")
    if profile_failures:
        failures.append("profile_failures")

    overlap_failures: list[str] = []
    pit_a_values: dict[tuple[str, str], tuple[float, str]] = {}
    if has_columns:
        for row in frame[frame["pit_grade"].eq("A")].itertuples():
            key = (str(row.series_id), str(row.reference_period))
            pit_a_values[key] = (float(row.value), str(row.unit))
    expected_overlap: dict[str, dict[str, Any]] = {}
    expected_overlap_counts = {"exact": 0, "rounding": 0, "revision": 0}
    for key in sorted(set(pit_a_values) & set(manual_values)):
        pit_a, unit_a = pit_a_values[key]
        pit_c = manual_values[key]
        unit_c = manual_units[key]
        difference = abs(pit_a - pit_c)
        category = _overlap_category(key[0], unit_a, unit_c, difference)
        expected_overlap_counts[category] += 1
        expected_overlap["|".join(key)] = {
            "pit_a": pit_a,
            "pit_a_unit": unit_a,
            "pit_c": pit_c,
            "pit_c_unit": unit_c,
            "absolute_difference": difference,
            "category": category,
            "pit_a_wins": True,
        }
        selected = frame[(frame["series_id"] == key[0]) & (frame["reference_period"] == key[1])]
        if len(selected) != 1 or str(selected.iloc[0]["pit_grade"]) != "A":
            overlap_failures.append(f"PIT-A does not win overlap: {'|'.join(key)}")
    actual_overlap = route.get("overlap") if isinstance(route.get("overlap"), dict) else {}
    actual_details = actual_overlap.get("details") if isinstance(actual_overlap.get("details"), list) else []
    actual_by_key = {str(item.get("key")): item for item in actual_details if isinstance(item, dict)}
    if actual_overlap.get("overlap_count") != len(expected_overlap) or actual_overlap.get("counts") != expected_overlap_counts or len(actual_by_key) != len(expected_overlap):
        overlap_failures.append("overlap summary")
    for key, expected_detail in expected_overlap.items():
        actual_detail = actual_by_key.get(key)
        if actual_detail is None:
            overlap_failures.append(f"missing overlap detail: {key}")
            continue
        for field in ("pit_a_unit", "pit_c_unit", "category", "pit_a_wins"):
            if actual_detail.get(field) != expected_detail[field]:
                overlap_failures.append(f"overlap {field}: {key}")
        for field in ("pit_a", "pit_c", "absolute_difference"):
            try:
                if not math.isclose(float(actual_detail.get(field)), float(expected_detail[field]), rel_tol=0.0, abs_tol=1e-12):
                    overlap_failures.append(f"overlap {field}: {key}")
            except (TypeError, ValueError):
                overlap_failures.append(f"overlap {field}: {key}")
    if overlap_failures:
        failures.append("overlap_failures")

    candidate_shas = {str(value).upper() for value in frame["raw_sha256"].dropna()} if "raw_sha256" in frame else set()
    if candidate_shas != manifest_shas:
        failures.append("candidate_manifest_sha_set")
    if manifest_failures:
        failures.append("manifest_failures")
    if audit.get("raw_hashes_valid") is not True:
        failures.append("audit_raw_hashes_invalid")
    pit_a_count = int((frame["pit_grade"] == "A").sum()) if "pit_grade" in frame else 0
    pit_c_count = int((frame["pit_grade"] == "C").sum()) if "pit_grade" in frame else 0
    checks = {
        "independent_expected_key_count": len(expected) == EXPECTED_TOTAL,
        "candidate_audit_key_equality": candidate_keys == observed == expected,
        "series_counts_exact": series_counts == {"CN.GDP.NOMINAL.YTD": 138, "CN.GDP.REAL.YOY": 134, "CN.INDUSTRIAL.VA.YOY": 309},
        "pit_a_c_counts": pit_a_count == 38 and pit_c_count == 543,
        "raw_hash_closure_exact": candidate_shas == manifest_shas,
        "pit_rows_valid": not pit_failures,
        "structural_omissions_exact": audit.get("structural_omissions") == expected_structural,
        "profiles_from_xlsx_exact": not profile_failures,
        "overlap_classification_exact": not overlap_failures,
        "research_ready_false": audit.get("research_ready") is False,
        "source_map_independent": source_map_path is None or source_map_keys == expected,
    }
    return {
        "passed": not failures,
        "checks": checks,
        "failures": sorted(set(failures)),
        "rows": int(len(frame)),
        "expected_periods_independent_count": len(expected),
        "observed_cells": len(candidate_keys),
        "series_counts": series_counts,
        "pit_a_rows": pit_a_count,
        "pit_c_rows": pit_c_count,
        "duplicate_primary_keys": duplicate_keys,
        "value_domain_failures": domain_failures,
        "pit_failure_count": len(pit_failures),
        "pit_failure_details": pit_failures,
        "profile_failure_details": profile_failures,
        "overlap_failure_details": overlap_failures,
        "manifest_count": len(_records(audit)),
        "candidate_raw_sha256_distinct_count": len(candidate_shas),
        "manifest_sha256_distinct_count": len(manifest_shas),
        "key_set_mismatch": mismatch,
        "research_ready": False,
    }


def _valid_enablement_timestamp(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except (TypeError, ValueError):
        return False


def validate_enablement_audit(audit_path: Path) -> dict[str, Any]:
    """Validate mechanism evidence without reading or constructing a candidate."""
    failures: list[str] = []
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"passed": False, "failures": [f"audit_readable:{exc}"]}
    if audit.get("run_mode") != "official_path_enablement" or audit.get("research_ready") is not False:
        failures.append("audit_mode_or_research_ready")
    budget = audit.get("request_budget", {})
    try:
        used = int(budget.get("used", -1))
    except (TypeError, ValueError):
        used = -1
    if budget.get("within_limit") is not True or used > 30:
        failures.append("request_budget")
    mechanisms = audit.get("mechanisms")
    if not isinstance(mechanisms, dict):
        failures.append("mechanisms_missing")
        mechanisms = {}
    records: list[dict[str, Any]] = []
    for name in ("release_history", "nbs_data_history"):
        mechanism = mechanisms.get(name, {})
        if not isinstance(mechanism, dict) or mechanism.get("status") not in {"VERIFIED", "BLOCKED", "NOT_NEEDED"}:
            failures.append(f"{name}_status")
            continue
        items = mechanism.get("page_requests", mechanism.get("requests", []))
        if name == "release_history" and isinstance(mechanism.get("search_requests"), list):
            items = list(mechanism["search_requests"]) + list(items)
        if not isinstance(items, list):
            failures.append(f"{name}_records")
            continue
        records.extend(item for item in items if isinstance(item, dict))
        if mechanism.get("status") == "VERIFIED" and any(item.get("status") != 200 for item in items if isinstance(item, dict)):
            failures.append(f"{name}_verified_non200")
    try:
        reconciled = sum(int(item.get("attempts", 1)) for item in records)
    except (TypeError, ValueError):
        reconciled = -1
    if reconciled != used:
        failures.append("request_count_not_reconciled")
    for record in records:
        url = str(record.get("url", ""))
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc.lower() not in OFFICIAL_HOSTS:
            failures.append("non_official_url")
        if not isinstance(record.get("status"), int):
            failures.append("status_not_integer")
        elif int(record["status"]) != 200:
            failures.append("http_non200")
        if int(record.get("status", 0)) == 200 and int(record.get("bytes", 1)) == 0:
            failures.append("empty_200_response")
        manifest_path = Path(str(record.get("manifest_path", "")))
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw = Path(str(manifest["raw_path"]))
            if "enablement" not in raw.parts or manifest.get("response", {}).get("status") != record.get("status"):
                failures.append("manifest_lineage")
            if int(manifest["bytes"]) != raw.stat().st_size or hashlib.sha256(raw.read_bytes()).hexdigest() != manifest.get("sha256"):
                failures.append("manifest_raw_hash")
        except (OSError, ValueError, KeyError, TypeError):
            failures.append("manifest_unreadable")
    release = mechanisms.get("release_history", {})
    samples = release.get("successful_pit_a_samples", []) if isinstance(release, dict) else []
    if not isinstance(samples, list):
        failures.append("release_samples_type")
        samples = []
    for sample in samples:
        if sample.get("pit_grade") != "A" or sample.get("status", 200) != 200 or not sample.get("publication_time_original"):
            failures.append("pit_a_publication_or_status")
        if sample.get("period") == "2011-02" and "1—2月份" in str(sample.get("page_title", "")):
            failures.append("2011_february_joint")
        if sample.get("period") == "2013-02" and "1—2月份" not in str(sample.get("page_title", "")):
            failures.append("2013_february_not_joint")
        if sample.get("period") == "2019-Q3" and set(sample.get("series", [])) != set(GDP_SERIES):
            failures.append("early_gdp_two_fields_missing")
    data = mechanisms.get("nbs_data_history", {})
    if isinstance(data, dict):
        for sample in data.get("pit_c_samples", []):
            if not (_valid_enablement_timestamp(sample.get("retrieved_at")) and sample.get("available_at") == sample.get("retrieved_at") and sample.get("tradable_at") == sample.get("retrieved_at")):
                failures.append("pit_c_backdated_availability")
    closure = audit.get("raw_hash_closure", {})
    if closure.get("valid") is not True or closure.get("failures"):
        failures.append("raw_hash_closure")
    return {"passed": not failures, "failures": sorted(set(failures)), "request_count": used, "release_sample_count": len(samples), "mechanism_status": {name: mechanisms.get(name, {}).get("status") for name in ("release_history", "nbs_data_history", "manual_download")}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enablement-audit", type=Path)
    parser.add_argument("--manual-candidate", type=Path)
    parser.add_argument("--manual-audit", type=Path)
    parser.add_argument("--candidate", type=Path, default=ROOT / "artifacts" / "macro_r011" / "shadow" / "w1_growth_output_full_range_candidate.parquet")
    parser.add_argument("--audit", type=Path, default=ROOT / "artifacts" / "macro_r011" / "audits" / "w1_growth_output_full_range_audit.json")
    parser.add_argument("--source-map", type=Path, default=ROOT / "artifacts" / "macro_r011" / "state" / "w1_growth_output_luna_full_candidate" / "w1_growth_output_full_range_source_map.json")
    args = parser.parse_args()
    if args.enablement_audit:
        result = validate_enablement_audit(args.enablement_audit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["passed"] else 1)
    if args.manual_candidate or args.manual_audit:
        if not args.manual_candidate or not args.manual_audit:
            parser.error("--manual-candidate and --manual-audit must be supplied together")
        result = validate_manual_candidate(args.manual_candidate, args.manual_audit, args.source_map)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if result["passed"] else 1)
    result = validate_full_candidate(args.candidate, args.audit, args.source_map)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
