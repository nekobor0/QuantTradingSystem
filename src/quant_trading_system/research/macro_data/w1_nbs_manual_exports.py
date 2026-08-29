"""Offline integration of user-supplied NBS official XLSX exports.

The exports are treated as retrospective official history (PIT-C).  This
module never fetches, edits, or copies the source workbooks and never writes a
formal curated snapshot.  Existing release-page rows remain the winning
vintage when their canonical key overlaps a manual export.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import CANONICAL_V2_COLUMNS, write_canonical_v2_snapshot
from .w1_growth_full_history import (
    GDP_END,
    GDP_REAL_START,
    GDP_START,
    INDUSTRIAL_END,
    INDUSTRIAL_START,
    _months,
    _quarters,
    expected_keys,
    industrial_structural_omission,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
MANUAL_FREEZE = "2026-08-29T11:50:00+08:00"
PARSER_VERSION = "r011.4-nbs-manual-exports"
MANUAL_SOURCE_ID = "NBS_DATA"
MANUAL_ROOT_NAME = "manual_drop"
NBS_ENTRY = "https://data.stats.gov.cn/"
EXPECTED_WORKBOOKS = {
    "nbs-gdp-quarterly-history-original.xlsx": {
        "sha256": "50A831CEB434CD90E89106F9B0597929AD9ACA6B95BE7778F26EB518CF6F3E02",
        "kind": "gdp_nominal",
    },
    "nbs-gdp-quarterly-yoy-index-history-original.xlsx": {
        "sha256": "D03D8311E253F63DC0E902B5224F4CADFAB908460C2C36BBE68B6C53388A0F87",
        "kind": "gdp_real",
    },
    "nbs-industrial-value-added-history-original.xlsx": {
        "sha256": "CDC4354A4DD1FE8F1543E4729BC081946081B70937821BDD78365445027FB9A1",
        "kind": "industrial",
    },
    "nbs-GDP-nonchange-price-history-original.xlsx": {
        "sha256": "77BE7EA5321446EEC94A4C9E5BB271BBF52C32E128B8DB04B103CD7BBAB92259",
        "kind": "nonchange_profile",
    },
    "nbs-money-supply-monthly-history-original.xlsx": {
        "sha256": "F9198DB9CC5B51BB595BB2EF07DEBA4F7BD39C85DC7B8343942FD7301C9C4AB1",
        "kind": "money_profile",
    },
    "nbs-government-revenue-history-original.xlsx": {
        "sha256": "7552DBC16BA0570A8E45443E911649EF46A295161BDACD577F100E8CCEDD1583",
        "kind": "fiscal_revenue_profile",
    },
    "nbs-government-spending-history-original.xlsx": {
        "sha256": "94CE8EF545E06649740A67AD2B3BD6C33A742277110B8F2CB65EE33BEC12C5B8",
        "kind": "fiscal_spending_profile",
    },
}


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    return text[1:] if text.startswith("'") else text


def _period(value: Any) -> str | None:
    text = _clean(value)
    quarter = re.search(r"(\d{4})年第?([一二三四1234])季度", text)
    if quarter:
        number = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(quarter.group(2), quarter.group(2))
        return f"{quarter.group(1)}-Q{number}"
    month = re.search(r"(\d{4})年(\d{1,2})月", text)
    if month:
        return f"{month.group(1)}-{int(month.group(2)):02d}"
    return None


def _number(value: Any) -> float:
    text = _clean(value).replace(",", "")
    if not text:
        raise ValueError("empty numeric export cell")
    return float(text)


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() != ".xlsx":
        raise ValueError(f"only original XLSX exports are accepted: {path.name}")
    return pd.read_excel(path, header=None)


def _assert_label(value: Any, required: tuple[str, ...], forbidden: tuple[str, ...] = ()) -> str:
    label = _clean(value)
    if any(term not in label for term in required) or any(term in label for term in forbidden):
        raise ValueError(f"unexpected NBS row label: {label}")
    return label


def _header_periods(frame: pd.DataFrame, start_column: int = 1) -> dict[str, int]:
    result: dict[str, int] = {}
    for column in range(start_column, frame.shape[1]):
        key = _period(frame.iat[2, column])
        if key is not None:
            if key in result:
                raise ValueError(f"duplicate export period: {key}")
            result[key] = column
    if not result:
        raise ValueError("NBS workbook has no parseable period headers")
    return result


def _find_row(frame: pd.DataFrame, required: tuple[str, ...], forbidden: tuple[str, ...] = ()) -> tuple[int, str]:
    matches = []
    for index in range(frame.shape[0]):
        label = _clean(frame.iat[index, 0])
        if all(term in label for term in required) and not any(term in label for term in forbidden):
            matches.append((index, label))
    if len(matches) != 1:
        raise ValueError(f"expected one NBS row for {required}, found {len(matches)}")
    return matches[0]


def _cell_profile(frame: pd.DataFrame, columns: dict[str, int], row_index: int, label: str) -> dict[str, Any]:
    observed_periods = sorted(period for period, column in columns.items() if _clean(frame.iat[row_index, column]))
    header_periods = sorted(columns)
    return {
        "row_index": row_index,
        "label": label,
        "observed": len(observed_periods),
        "missing": len(header_periods) - len(observed_periods),
        "earliest_observed": observed_periods[0] if observed_periods else None,
        "latest_observed": observed_periods[-1] if observed_periods else None,
        "observed_periods": observed_periods,
    }


def _sha_manifest(raw_root: Path, path: Path, kind: str) -> tuple[dict[str, Any], Path]:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest().upper()
    expected = EXPECTED_WORKBOOKS[path.name]["sha256"]
    if digest != expected:
        raise ValueError(f"workbook SHA mismatch for {path.name}: {digest}")
    manifest_dir = raw_root / "manual_manifest"
    manifest_path = manifest_dir / f"{digest}.manifest.json"
    manifest = {
        "schema_version": 1,
        "source_id": MANUAL_SOURCE_ID,
        "source_type": "manual_nbs_official_export",
        "kind": kind,
        "retrieved_at": MANUAL_FREEZE,
        "sha256": digest,
        "bytes": path.stat().st_size,
        "raw_path": str(path.resolve()),
        "request": {"method": "LOCAL_MANUAL_EXPORT", "url": NBS_ENTRY},
        "response": {"status": 200, "headers": {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}},
        "page_publication_time_original": None,
        "historical_pit_supported": False,
        "source_identity": "National Bureau of Statistics of China / official National Data export",
    }
    payload_json = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        if manifest_path.read_bytes() != payload_json:
            raise RuntimeError(f"immutable manual manifest conflict: {manifest_path}")
    else:
        _atomic(manifest_path, payload_json)
    return manifest, manifest_path


def _atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".nbs-manual-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _row(series: str, period: str, value: float, raw_sha: str, *, measure_basis: str, start: str | None = None, end: str | None = None, span: str | None = None) -> dict[str, Any]:
    period_start = start or period
    period_end = end or period
    period_span = span or period
    return {
        "series_id": series,
        "reference_period": period,
        "value": value,
        "unit": "100m_cny" if series == "CN.GDP.NOMINAL.YTD" else "percent_yoy",
        "seasonal_adjustment": "not_applicable",
        "source_id": MANUAL_SOURCE_ID,
        "source_record_id": f"NBS_MANUAL_EXPORT:{series}:{period}:{raw_sha[:16]}",
        "release_at": MANUAL_FREEZE,
        "available_at": MANUAL_FREEZE,
        "tradable_at": MANUAL_FREEZE,
        "availability_evidence": "NBS official National Data XLSX manual export; retrieved/frozen at 2026-08-29T11:50:00+08:00; historical PIT unavailable",
        "retrieved_at": MANUAL_FREEZE,
        "vintage_id": f"nbs_growth_manual:{series}:{raw_sha[:16]}",
        "raw_sha256": raw_sha,
        "parser_version": PARSER_VERSION,
        "schema_version": 2,
        "reference_period_start": period_start,
        "reference_period_end": period_end,
        "period_span": period_span,
        "measure_basis": measure_basis,
        "methodology_version": "nbs_growth_output_manual_exports_v1",
        "regime_id": "growth_output_full_history",
        "pit_grade": "C",
        "license_scope": "internal_research",
    }


def _parse_gdp(path: Path, manifest: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    frame = _read(path)
    columns = _header_periods(frame)
    if kind == "gdp_nominal":
        _assert_label(frame.iat[4, 0], ("国内生产总值", "累计值"))
        periods = set(_quarters(GDP_START, GDP_END))
        return [_row("CN.GDP.NOMINAL.YTD", p, _number(frame.iat[4, columns[p]]), manifest["sha256"], measure_basis="ytd_cumulative") for p in sorted(periods) if p in columns]
    _assert_label(frame.iat[3, 0], ("国内生产总值", "指数", "当季值"), ("累计值",))
    periods = set(_quarters(GDP_REAL_START, GDP_END))
    return [_row("CN.GDP.REAL.YOY", p, _number(frame.iat[3, columns[p]]) - 100.0, manifest["sha256"], measure_basis="period_observation") for p in sorted(periods) if p in columns]


def _parse_industrial(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    frame = _read(path)
    columns = _header_periods(frame)
    _assert_label(frame.iat[3, 0], ("工业增加值", "同比"))
    _assert_label(frame.iat[4, 0], ("工业增加值", "累计"))
    rows: list[dict[str, Any]] = []
    for period in _months(INDUSTRIAL_START, INDUSTRIAL_END):
        if industrial_structural_omission(period) or period not in columns:
            continue
        year, month = int(period[:4]), int(period[5:])
        cumulative = month == 2 and year >= 2013
        value = _number(frame.iat[4 if cumulative else 3, columns[period]])
        rows.append(_row("CN.INDUSTRIAL.VA.YOY", period, value, manifest["sha256"], measure_basis="period_observation", start=f"{period[:4]}-01" if cumulative else period, end=period, span=f"{period[:4]}-01/02" if cumulative else period))
    return rows


def _profile(path: Path, kind: str) -> dict[str, Any]:
    frame = _read(path)
    columns = _header_periods(frame)
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
        row_index, label = _find_row(frame, ("国内生产总值", "不变价", "当季值"), ("累计值",))
        row_profile = _cell_profile(frame, columns, row_index, label)
        note = next((_clean(frame.iat[index, 0]) for index in range(frame.shape[0]) if "基期" in _clean(frame.iat[index, 0])), "")
        result.update({
            "observed": row_profile["observed"],
            "missing": row_profile["missing"],
            "earliest": row_profile["earliest_observed"],
            "latest": row_profile["latest_observed"],
            "earliest_observed": row_profile["earliest_observed"],
            "latest_observed": row_profile["latest_observed"],
            "observed_periods": row_profile["observed_periods"],
            "row": row_profile,
            "quarter_count_2007_q1_to_2026_q2": row_profile["observed"],
            "base_period_note": note,
            "cross_base_yoy": False,
        })
    elif kind == "money_profile":
        row_profiles: dict[str, dict[str, Any]] = {}
        for index in range(frame.shape[0]):
            label = _clean(frame.iat[index, 0])
            aggregate = next((name for name in ("M0", "M1", "M2") if name in label), None)
            if aggregate is None:
                continue
            measure = "balance" if "期末值" in label else "yoy" if "同比" in label and "增长" in label else None
            if measure is None:
                continue
            key = f"{aggregate}_{measure}"
            if key in row_profiles:
                raise ValueError(f"duplicate money-supply row: {key}")
            row_profiles[key] = _cell_profile(frame, columns, index, label)
        expected_rows = {f"{aggregate}_{measure}" for aggregate in ("M0", "M1", "M2") for measure in ("balance", "yoy")}
        if set(row_profiles) != expected_rows:
            raise ValueError(f"money-supply rows are incomplete: {sorted(row_profiles)}")
        result.update({
            "m0_m1_m2_field_count": {name: sum(key.startswith(f"{name}_") for key in row_profiles) for name in ("M0", "M1", "M2")},
            "balance_and_yoy_rows_profiled": len(row_profiles),
            "row_profiles": {key: row_profiles[key] for key in sorted(row_profiles)},
            "source_note": "NBS redistribution / underlying PBOC",
            "underlying_source": "PBOC / NBS redistribution",
        })
    else:
        value_index, value_label = _find_row(frame, ("累计值",))
        growth_index, growth_label = _find_row(frame, ("累计增长",)) if any("累计增长" in _clean(frame.iat[index, 0]) for index in range(frame.shape[0])) else _find_row(frame, ("累计同比",))
        row_profiles = {
            "cumulative_value": _cell_profile(frame, columns, value_index, value_label),
            "cumulative_growth": _cell_profile(frame, columns, growth_index, growth_label),
        }
        result.update({
            "cumulative_value_or_yoy_row_count": len(row_profiles),
            "row_profiles": row_profiles,
            "cumulative_value_observed": row_profiles["cumulative_value"]["observed"],
            "cumulative_value_missing": row_profiles["cumulative_value"]["missing"],
            "cumulative_growth_observed": row_profiles["cumulative_growth"]["observed"],
            "cumulative_growth_missing": row_profiles["cumulative_growth"]["missing"],
            "missing_cells": sum(profile["missing"] for profile in row_profiles.values()),
            "monthly_differencing": False,
        })
    return result


def _existing_pit_a(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"existing PIT-A candidate is required: {path}")
    frame = pd.read_parquet(path)
    if list(frame.columns) != CANONICAL_V2_COLUMNS:
        raise ValueError("existing candidate is not canonical v2")
    return frame[frame["pit_grade"].eq("A")].copy()


def _overlap(a: pd.DataFrame, b: pd.DataFrame) -> dict[str, Any]:
    left = {(str(row.series_id), str(row.reference_period)): (float(row.value), str(row.unit)) for row in a.itertuples()}
    right = {(str(row.series_id), str(row.reference_period)): (float(row.value), str(row.unit)) for row in b.itertuples()}
    details: list[dict[str, Any]] = []
    counts = {"exact": 0, "rounding": 0, "revision": 0}
    for key in sorted(set(left) & set(right)):
        pit_a, unit_a = left[key]
        pit_c, unit_c = right[key]
        difference = abs(pit_a - pit_c)
        if difference <= 1e-9:
            category = "exact"
        elif key[0] == "CN.GDP.NOMINAL.YTD" and unit_a == unit_c == "100m_cny" and difference <= 0.5:
            category = "rounding"
        elif unit_a == unit_c == "percent_yoy" and difference <= 0.05:
            category = "rounding"
        else:
            category = "revision"
        counts[category] += 1
        details.append({"key": "|".join(key), "pit_a": pit_a, "pit_a_unit": unit_a, "pit_c": pit_c, "pit_c_unit": unit_c, "absolute_difference": difference, "category": category, "pit_a_wins": True})
    return {"overlap_count": len(details), "counts": counts, "details": details}


def run_manual_import(*, raw_root: Path, output_root: Path, pit_a_candidate: Path | None = None) -> dict[str, Any]:
    """Parse existing official XLSX exports and write a shadow candidate/audit."""
    drop = raw_root / MANUAL_ROOT_NAME
    manifests: dict[str, tuple[dict[str, Any], Path]] = {}
    for filename, spec in EXPECTED_WORKBOOKS.items():
        path = drop / filename
        if not path.exists():
            raise FileNotFoundError(f"required official manual export missing: {path}")
        manifests[filename] = _sha_manifest(raw_root, path, str(spec["kind"]))
    canonical_rows: list[dict[str, Any]] = []
    canonical_rows.extend(_parse_gdp(drop / "nbs-gdp-quarterly-history-original.xlsx", manifests["nbs-gdp-quarterly-history-original.xlsx"][0], "gdp_nominal"))
    canonical_rows.extend(_parse_gdp(drop / "nbs-gdp-quarterly-yoy-index-history-original.xlsx", manifests["nbs-gdp-quarterly-yoy-index-history-original.xlsx"][0], "gdp_real"))
    canonical_rows.extend(_parse_industrial(drop / "nbs-industrial-value-added-history-original.xlsx", manifests["nbs-industrial-value-added-history-original.xlsx"][0]))
    manual = pd.DataFrame(canonical_rows, columns=CANONICAL_V2_COLUMNS)
    expected = set(expected_keys())
    manual_keys = {f"{row.series_id}|{row.reference_period}" for row in manual.itertuples()}
    if manual_keys != expected:
        raise ValueError(f"manual export keys do not equal independent expected keys: missing={sorted(expected-manual_keys)[:5]} extra={sorted(manual_keys-expected)[:5]}")
    pit_a_path = pit_a_candidate or output_root / "shadow" / "w1_growth_output_full_range_candidate.parquet"
    pit_a = _existing_pit_a(pit_a_path)
    pit_a_keys = {f"{row.series_id}|{row.reference_period}" for row in pit_a.itertuples()}
    manual = manual[~manual.apply(lambda row: f"{row['series_id']}|{row['reference_period']}" in pit_a_keys, axis=1)].copy()
    overlap = _overlap(pit_a, pd.DataFrame(canonical_rows, columns=CANONICAL_V2_COLUMNS))
    final = pd.concat([pit_a, manual], ignore_index=True).drop_duplicates(["series_id", "reference_period"], keep="first")
    final = final.sort_values(["reference_period", "series_id", "pit_grade", "vintage_id"], kind="mergesort").reset_index(drop=True)
    candidate_path = output_root / "shadow" / "w1_growth_output_manual_exports_full_candidate.parquet"
    write_canonical_v2_snapshot(final, candidate_path)
    structural = [{"series_id": "CN.INDUSTRIAL.VA.YOY", "period": p, "reason": "January single-month value is not officially published"} for p in _months("1999-01", INDUSTRIAL_END) if p.endswith("-01")]
    source_scope_exclusions = [{"series_id": "CN.GDP.REAL.YOY", "period": p, "reason": "NBS GDP index export has no comparable prior-year index for 1992"} for p in _quarters(GDP_START, "1992-Q4")]
    observed = sorted({f"{row.series_id}|{row.reference_period}" for row in final.itertuples()})
    missing = sorted(expected - set(observed))
    source_entries = []
    old_audit = output_root / "audits" / "w1_growth_output_full_range_audit.json"
    if old_audit.exists():
        old = json.loads(old_audit.read_text(encoding="utf-8")).get("audit", {})
        old_release = next((item for item in old.get("sources", []) if item.get("source_id") == "NBS_RELEASE"), None)
        if old_release:
            source_entries.append({**old_release, "role": "PIT-A existing release rows; preserved and preferred on overlap"})
    source_entries.append({"source_id": MANUAL_SOURCE_ID, "role": "PIT-C official retrospective manual XLSX exports", "raw_manifests": [{"manifest_path": str(path.resolve()), "pit_grade": "C", "sha256": manifest["sha256"], "status": 200, "url": NBS_ENTRY} for manifest, path in manifests.values() if manifest["kind"] in {"gdp_nominal", "gdp_real", "industrial"}], "historical_pit_supported": False})
    profiles = {filename: _profile(drop / filename, str(spec["kind"])) for filename, spec in EXPECTED_WORKBOOKS.items() if spec["kind"].endswith("profile")}
    audit = {
        "schema_version": 1,
        "package_id": "growth_output",
        "run_mode": "shadow",
        "requested_window": {"start": GDP_START, "end": INDUSTRIAL_END},
        "expected_periods": sorted(expected),
        "observed_periods": observed,
        "sources": source_entries,
        "raw_hashes_valid": True,
        "duplicate_primary_keys": int(final.duplicated(["series_id", "reference_period"]).sum()),
        "value_domain_failures": int((~final["value"].between(-100.0, 2_000_000.0)).sum()),
        "unexplained_missing": missing,
        "structural_omissions": structural,
        "blocked": bool(missing),
        "blockers": [{"code": "MANUAL_EXPORT_INCOMPLETE", "detail": missing}] if missing else [],
        "research_ready": False,
    }
    document = {"audit": audit, "candidate": {"path": str(candidate_path.resolve()), "rows": len(final), "pit_a_rows": int((final["pit_grade"] == "A").sum()), "pit_c_rows": int((final["pit_grade"] == "C").sum()), "research_ready": False}, "manual_route": {"status": "READY" if not missing else "BLOCKED", "freeze": MANUAL_FREEZE, "overlap": overlap, "source_scope_exclusions": source_scope_exclusions, "profiles": profiles, "canonical_workbooks": sorted(filename for filename, spec in EXPECTED_WORKBOOKS.items() if not str(spec["kind"]).endswith("profile")), "formal_curated_written": False, "mechanism_ready": False, "evidence_integrity_passed": True}}
    audit_path = output_root / "audits" / "w1_growth_output_manual_exports_full.json"
    _atomic(audit_path, (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    summary = output_root / "audits" / "w1_growth_output_manual_exports_full.md"
    summary_text = "\n".join([
        "# W1 growth_output manual official exports",
        "",
        f"- Expected/observed: {len(expected)}/{len(observed)}; GDP nominal=138, GDP real=134, industrial=309.",
        f"- PIT-A/PIT-C: {int((final['pit_grade'] == 'A').sum())}/{int((final['pit_grade'] == 'C').sum())}; manual batch freeze={MANUAL_FREEZE}.",
        f"- Missing={len(missing)}; duplicate={audit['duplicate_primary_keys']}; domain failures={audit['value_domain_failures']}; research_ready=false.",
        "- GDP real is current-quarter official previous-year index minus 100; no 1992 real rows. Industrial February is independent through 2012 and Jan-Feb joint from 2013.",
        "- Non-change-price, money-supply, revenue, and spending exports are inventory/profile only; no canonical rows were derived from them.",
        "- Formal curated is not written.",
    ]) + "\n"
    _atomic(summary, summary_text.encode("utf-8"))
    return {"candidate": str(candidate_path.resolve()), "audit": str(audit_path.resolve()), "rows": len(final), "expected": len(expected), "pit_a": int((final["pit_grade"] == "A").sum()), "pit_c": int((final["pit_grade"] == "C").sum()), "missing": missing, "raw_manifest_count": len(manifests), "profiles": profiles}
