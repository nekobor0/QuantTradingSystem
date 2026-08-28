"""Full-history, audit-only growth-output candidate mechanics."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from http.client import HTTPException, IncompleteRead
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import pandas as pd

from .contracts import CANONICAL_V2_COLUMNS, validate_canonical_v2, write_canonical_v2_snapshot
from .w1_execution import build_audit, validate_audit
from .w1_growth_history import parse_gdp_release, parse_industrial_release


RAW_SOURCE_ID = "nbs_growth_output_official"
RELEASE_SOURCE_ID = "NBS_RELEASE"
DATA_SOURCE_ID = "NBS_DATA"
GDP_SERIES = ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY")
INDUSTRIAL_SERIES = ("CN.INDUSTRIAL.VA.YOY",)
GDP_START = "1992-Q1"
GDP_END = "2026-Q2"
INDUSTRIAL_START = "1998-01"
INDUSTRIAL_END = "2026-07"
NBS_DATA_PROBE = "https://data.stats.gov.cn/easyquery.htm?cn=E0103&zb=A0201&sj=2024"
INDUSTRIAL_DEFINITION = "https://www.stats.gov.cn/zs/tjws/zytjzbqs/gysczzsd/202409/t20240909_1956328.html"
OFFICIAL_HOSTS = {"www.stats.gov.cn", "stats.gov.cn", "data.stats.gov.cn"}

try:
    from zoneinfo import ZoneInfo

    SHANGHAI = ZoneInfo("Asia/Shanghai")
except ImportError:  # pragma: no cover
    SHANGHAI = timezone.utc


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


def industrial_structural_omission(period: str) -> bool:
    year, month = int(period[:4]), int(period[5:7])
    return year >= 2005 and month == 1


def industrial_provisional_period(period: str) -> bool:
    year, month = int(period[:4]), int(period[5:7])
    return 1998 <= year <= 2004 and month == 1


def expected_periods() -> dict[str, list[str]]:
    return {
        "gdp": _quarters(GDP_START, GDP_END),
        "industrial": [period for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if not industrial_structural_omission(period)],
    }


def expected_keys() -> list[str]:
    periods = expected_periods()
    return [f"{series}|{period}" for period in periods["gdp"] for series in GDP_SERIES] + [f"CN.INDUSTRIAL.VA.YOY|{period}" for period in periods["industrial"]]


def build_source_map() -> dict[str, Any]:
    periods = expected_periods()
    all_industrial_periods = _months(INDUSTRIAL_START, INDUSTRIAL_END)
    structural_periods = [period for period in all_industrial_periods if industrial_structural_omission(period)]
    provisional_periods = [period for period in all_industrial_periods if industrial_provisional_period(period)]
    return {
        "schema_version": 1,
        "package_id": "growth_output",
        "status": "AUDIT_ONLY_FULL_HISTORY_CANDIDATE",
        "research_ready": False,
        "scope": {
            "gdp": {"start": GDP_START, "end": GDP_END, "period_count": len(periods["gdp"]), "expected_cells": len(periods["gdp"]) * 2},
            "industrial": {"start": INDUSTRIAL_START, "end": INDUSTRIAL_END, "period_count": len(periods["industrial"]), "calendar_month_count": len(_months(INDUSTRIAL_START, INDUSTRIAL_END)), "expected_cells": len(periods["industrial"])},
            "expected_key_count": len(expected_keys()),
            "industrial_period_classes": {
                "expected_periods": periods["industrial"],
                "structural_omission_periods": structural_periods,
                "provisional_periods_awaiting_official_evidence": provisional_periods,
            },
        },
        "sources": {
            "NBS_RELEASE": {
                "authority": "National Bureau of Statistics of China",
                "hosts": ["www.stats.gov.cn", "stats.gov.cn"],
                "role": "PIT-A contemporaneous release page",
                "discovery": "official NBS release index/search pages and existing archived official release URLs; archived index pages are parsed before reuse",
                "publication_evidence": "printed page date/time; release/available/tradable cannot precede it",
                "pit_a_earliest": None,
                "pit_a_latest": None,
                "evidence_urls": [
                    "https://www.stats.gov.cn/sj/zxfb/202410/t20241019_1957083.html",
                    "https://www.stats.gov.cn/sj/zxfb/202507/t20250716_1960426.html",
                ],
            },
            "NBS_DATA": {
                "authority": "National Bureau of Statistics of China",
                "hosts": ["data.stats.gov.cn"],
                "role": "PIT-C official retrospective query/history",
                "query_url": NBS_DATA_PROBE,
                "publication_vintage": "actual retrieval time only; database refresh is not a release timestamp",
                "pit_c_earliest": None,
                "pit_c_latest": None,
            },
        },
        "series": {
            "CN.GDP.NOMINAL.YTD": {
                "definition": "official GDP YTD cumulative amount, unit 100m_cny; a single-quarter amount is not accepted",
                "inception": GDP_START,
                "scope_basis": "official GDP release/database history is scoped from 1992-Q1; source must expose cumulative/YTD amount",
                "pit_a_window": None,
                "pit_c_window": None,
                "pit_status": "unknown_pending_official_discovery",
                "unexplained_policy": "missing unless archived official response exposes the YTD cumulative field",
            },
            "CN.GDP.REAL.YOY": {
                "definition": "official quarterly GDP real year-on-year rate, unit percent",
                "inception": GDP_START,
                "scope_basis": "official GDP release/database history is scoped from 1992-Q1",
                "pit_a_window": None,
                "pit_c_window": None,
                "pit_status": "unknown_pending_official_discovery",
                "unexplained_policy": "missing unless archived official response exposes the quarterly real YoY field",
            },
            "CN.INDUSTRIAL.VA.YOY": {
                "definition": "official scale-above industrial value-added year-on-year rate, unit percent",
                "inception": INDUSTRIAL_START,
                "scope_basis": "official definition evidence records the scale-above regime split in 1998; pre-1998 industrial VA is not silently mixed",
                "jan_feb_rule": "1998-02 through 2011-02 are independent YYYY-02 observations; from 2012-02 onward YYYY-02 is the Jan-Feb joint observation with period_span=YYYY-01/02; no YYYY-01 is synthesized",
                "february_regimes": [
                    {"through": "2011-02", "reference_period": "YYYY-02", "period_span": "YYYY-02", "status": "independent_monthly_observation"},
                    {"from": "2012-02", "reference_period": "YYYY-02", "period_span": "YYYY-01/02", "status": "jan_feb_joint_observation"},
                ],
                "structural_omissions": [
                    {"rule": "YYYY-01, YYYY>=2005", "reason": "January single-month release is not published"},
                ],
                "provisional_periods": [
                    {"rule": "YYYY-01, 1998<=YYYY<=2004", "reason": "expected by scope; awaits direct official evidence"},
                ],
                "structural_omission_periods": structural_periods,
                "provisional_periods_awaiting_official_evidence": provisional_periods,
                "definition_evidence_url": INDUSTRIAL_DEFINITION,
                "pit_a_window": None,
                "pit_c_window": None,
                "pit_status": "unknown_pending_official_discovery",
                "unexplained_policy": "missing unless archived official release/history exposes the scale-above field",
            },
        },
        "methodology_regimes": [
            "GDP nominal stores only an official cumulative/YTD field; no single-quarter-to-YTD accumulation.",
            "Industrial scope uses the official scale-above regime inception evidence and preserves Jan-Feb as one observation.",
            "PIT-A is contemporaneous page-time evidence; official retrospective history is PIT-C and is never backdated to its reference period.",
        ],
        "periods": periods,
        "expected_keys": expected_keys(),
    }


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".growth-full-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    _atomic_bytes(path, (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def source_map_path(output_root: Path) -> Path:
    return output_root / "state" / "w1_growth_output_luna_full_candidate" / "w1_growth_output_full_range_source_map.json"


def write_source_map(output_root: Path) -> Path:
    path = source_map_path(output_root)
    atomic_json(path, build_source_map())
    return path


def _fetch(url: str, fetcher: Callable[[str], tuple[int, dict[str, str], bytes, str | None]] | None = None) -> tuple[int, dict[str, str], bytes, str | None]:
    if fetcher is not None:
        return fetcher(url)
    request = Request(url, headers={"User-Agent": "QuantTradingSystem-W1-growth-full/1.0", "Accept": "text/html,application/xhtml+xml"})
    last_error: str | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                return int(response.status), dict(response.headers.items()), response.read(), None
        except HTTPError as exc:
            body = exc.read()
            last_error = f"HTTPError: {exc.code}"
            if attempt == 2 or exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                return int(exc.code), dict(exc.headers.items()), body, last_error
        except (URLError, TimeoutError, OSError, HTTPException, IncompleteRead) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 2:
                return 0, {}, b"", last_error
    return 0, {}, b"", last_error or "official fetch failed"


def archive_response(output_root: Path, *, url: str, status: int, headers: dict[str, str], payload: bytes, error: str | None, source_type: str) -> dict[str, Any]:
    if urlsplit(url).scheme != "https" or urlsplit(url).netloc.lower() not in OFFICIAL_HOSTS:
        raise ValueError(f"non-official URL: {url}")
    digest = hashlib.sha256(payload).hexdigest()
    directory = output_root / "raw" / RAW_SOURCE_ID / source_type / digest[:2]
    raw_path = directory / f"{digest}.html"
    if raw_path.exists() and raw_path.read_bytes() != payload:
        raise RuntimeError(f"immutable raw collision: {raw_path}")
    if not raw_path.exists():
        _atomic_bytes(raw_path, payload)
    captured = datetime.now(timezone.utc)
    manifest = {
        "schema_version": 1,
        "source_id": DATA_SOURCE_ID if "data.stats.gov.cn" in url else RELEASE_SOURCE_ID,
        "source_type": source_type,
        "retrieved_at": captured.isoformat(),
        "sha256": digest,
        "bytes": len(payload),
        "raw_path": str(raw_path.resolve()),
        "request": {"method": "GET", "url": url},
        "response": {"status": status, "headers": {key.lower(): value for key, value in headers.items() if key.lower() in {"content-type", "date", "etag", "last-modified"}}},
        "discovery_mechanism": "official_nbs_source_map_probe",
        "page_publication_time_original": None,
        "error": error,
    }
    manifest_path = directory / f"{digest}.{captured.strftime('%Y%m%dT%H%M%S%fZ')}.manifest.json"
    _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {"manifest": manifest, "manifest_path": str(manifest_path.resolve()), "raw_path": str(raw_path.resolve())}


def _title(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split()) if match else ""


def _visible(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def validate_industrial_layout(payload: bytes, period: str) -> None:
    """Reject a February parser/page-layout mismatch at the source boundary."""
    if not re.fullmatch(r"20\d{2}-\d{2}", period):
        raise ValueError(f"invalid industrial period: {period}")
    context = _title(payload) + " " + _visible(payload)
    year, month = int(period[:4]), int(period[5:7])
    joint = bool(re.search(r"1\s*[—－-]\s*2\s*月份", context))
    if month != 2:
        return
    if year >= 2012 and not joint:
        raise ValueError(f"{period} must use the 1—2月份 joint layout")
    if year <= 2011 and joint:
        raise ValueError(f"{period} must use the independent 2月份 layout")


def _release_manifests(output_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted((output_root / "raw" / RAW_SOURCE_ID).rglob("*.manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            url = str(manifest["request"]["url"])
            digest = str(manifest["sha256"])
            if manifest.get("source_type") != "release" or not url.startswith("https://www.stats.gov.cn/") or manifest["response"]["status"] != 200 or (url, digest) in seen:
                continue
            raw = Path(str(manifest["raw_path"]))
            if not raw.exists() or hashlib.sha256(raw.read_bytes()).hexdigest() != digest:
                continue
            seen.add((url, digest))
            result.append((path, manifest))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def _archived_index_urls(output_root: Path) -> set[str]:
    """Extract official release URLs from already archived official indexes."""
    urls: set[str] = set()
    for path in sorted((output_root / "raw" / RAW_SOURCE_ID).rglob("*.manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("source_type") != "index" or manifest.get("response", {}).get("status") != 200:
                continue
            payload = Path(str(manifest["raw_path"])).read_bytes()
            text = payload.decode("utf-8", errors="replace")
            for href in re.findall(r"href=[\"']([^\"']+)[\"']", text, flags=re.I):
                candidate = urljoin(str(manifest["request"]["url"]), html.unescape(href))
                if urlsplit(candidate).netloc.lower() in {"www.stats.gov.cn", "stats.gov.cn"} and candidate.endswith(".html") and "index" not in candidate.rsplit("/", 1)[-1]:
                    urls.add(candidate)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return urls


def _row(record: dict[str, Any], period: str, parsed: Any, manifest: dict[str, Any], url: str) -> dict[str, Any]:
    series_id = str(record["series_id"])
    industrial_february = series_id == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-02")
    joint = industrial_february and int(period[:4]) >= 2012
    span = f"{period[:4]}-01/02" if joint else period
    return {
        "series_id": series_id,
        "reference_period": period,
        "value": float(record["value"]),
        "unit": record["unit"],
        "seasonal_adjustment": "not_applicable",
        "source_id": RELEASE_SOURCE_ID,
        "source_record_id": f"NBS_RELEASE:{hashlib.sha256(url.encode()).hexdigest()[:16]}:{series_id}",
        "release_at": parsed.publication_at,
        "available_at": parsed.publication_at,
        "tradable_at": parsed.publication_at,
        "availability_evidence": f"official NBS release publication timestamp: {parsed.publication_original}",
        "retrieved_at": str(manifest["retrieved_at"]),
        "vintage_id": f"nbs_growth_full:release:{period}:{manifest['sha256'][:16]}",
        "raw_sha256": str(manifest["sha256"]),
        "parser_version": "w1_growth_output_full_v1",
        "schema_version": 2,
        "reference_period_start": f"{period[:4]}-01" if joint else period,
        "reference_period_end": period,
        "period_span": span,
        "measure_basis": record["measure_basis"],
        "methodology_version": "nbs_growth_output_full_pit_layered_v1",
        "regime_id": "growth_output_full_history",
        "pit_grade": "A",
        "license_scope": "internal_research",
    }


def _manifest_hash_failures(records: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for record in records:
        try:
            manifest = json.loads(Path(str(record["manifest_path"])).read_text(encoding="utf-8"))
            raw = Path(str(manifest["raw_path"]))
            if int(manifest["bytes"]) != raw.stat().st_size or hashlib.sha256(raw.read_bytes()).hexdigest() != manifest["sha256"]:
                failures.append(str(record["manifest_path"]))
        except (OSError, ValueError, KeyError, TypeError):
            failures.append(str(record.get("manifest_path", "")))
    return failures


def run_full_candidate(output_root: Path, *, fetch_probes: bool = False, fetcher: Callable[[str], tuple[int, dict[str, str], bytes, str | None]] | None = None) -> dict[str, Any]:
    map_path = write_source_map(output_root)
    source_map = json.loads(map_path.read_text(encoding="utf-8"))
    periods = expected_periods()
    expected = expected_keys()
    probe_records: list[dict[str, Any]] = []
    if fetch_probes:
        for url, source_type in ((NBS_DATA_PROBE, "source_map_probe"), (INDUSTRIAL_DEFINITION, "definition_probe")):
            status, headers, payload, error = _fetch(url, fetcher)
            captured = archive_response(output_root, url=url, status=status, headers=headers, payload=payload, error=error, source_type=source_type)
            probe_records.append({"url": url, "status": status, "bytes": len(payload), "sha256": captured["manifest"]["sha256"], "manifest_path": captured["manifest_path"], "pit_grade": "C" if "data.stats.gov.cn" in url else "A", "error": error})
    archived_index_urls = _archived_index_urls(output_root)
    release_records: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    selected_periods: set[str] = set()
    for manifest_path, manifest in _release_manifests(output_root):
        url = str(manifest["request"]["url"])
        payload = Path(str(manifest["raw_path"])).read_bytes()
        record = {"url": url, "status": manifest["response"]["status"], "sha256": manifest["sha256"], "manifest_path": str(manifest_path.resolve()), "pit_grade": "A", "publication_time_original": manifest.get("page_publication_time_original"), "discovered_by_archived_index": url in archived_index_urls}
        release_records.append(record)
        context = _title(payload) + " " + _visible(payload)
        try:
            quarter_match = re.search(r"(20\d{2})\s*年\s*([一二三四1234])\s*(?:季度|季)", context)
            industrial_match = re.search(r"(20\d{2})\s*年\s*(?:1\s*[—－-]\s*(\d{1,2})|(?:(\d{1,2}))\s*)月份", context)
            if quarter_match:
                quarter = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(quarter_match.group(2), quarter_match.group(2))
                period = f"{quarter_match.group(1)}-Q{quarter}"
                if period not in periods["gdp"] or period in selected_periods:
                    continue
                parsed = parse_gdp_release(payload, period)
            elif industrial_match:
                month = industrial_match.group(2) or industrial_match.group(3)
                period = f"{industrial_match.group(1)}-{int(month):02d}"
                if period not in periods["industrial"] or period in selected_periods:
                    continue
                validate_industrial_layout(payload, period)
                parsed = parse_industrial_release(payload, period)
            else:
                continue
            selected_periods.add(period)
            for item in parsed.rows:
                rows.append(_row(item, period, parsed, manifest, url))
        except (ValueError, IndexError, ImportError) as exc:
            parse_failures.append({"url": url, "manifest_path": str(manifest_path.resolve()), "error": f"{type(exc).__name__}: {exc}"})
    frame = pd.DataFrame(rows, columns=CANONICAL_V2_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["reference_period", "series_id", "vintage_id"], kind="mergesort").reset_index(drop=True)
    observed = sorted({f"{row['series_id']}|{row['reference_period']}" for row in rows})
    missing = sorted(set(expected) - set(observed))
    duplicates = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not frame.empty else 0
    domain_failures = int((~frame["value"].between(-100.0, 2_000_000.0)).sum()) if not frame.empty else 0
    canonical = validate_canonical_v2(frame) if not frame.empty else {"passed": False, "failures": ["empty_frame"], "rows": 0}
    all_manifests = release_records + probe_records
    hash_failures = _manifest_hash_failures(all_manifests)
    structural = [{"series_id": "CN.INDUSTRIAL.VA.YOY", "period": period, "reason": "January single-month value is not officially published" if period.endswith("-01") else "February observation is Jan-Feb joint, not February-only"} for period in _months(INDUSTRIAL_START, INDUSTRIAL_END) if industrial_structural_omission(period)]
    blockers: list[dict[str, Any]] = []
    if missing:
        blockers.append({"code": "OFFICIAL_HISTORY_INCOMPLETE", "detail": "independent full-range expected keys are not all covered by archived official release/history responses"})
    if any(item["status"] != 200 for item in probe_records):
        blockers.append({"code": "OFFICIAL_DATA_PROBE_FAILED", "detail": probe_records})
    if parse_failures or hash_failures or duplicates or domain_failures or not canonical["passed"]:
        blockers.append({"code": "FULL_CANDIDATE_EVIDENCE_INVALID", "detail": {"parse_failures": parse_failures, "hash_failures": hash_failures, "duplicate_primary_keys": duplicates, "value_domain_failures": domain_failures, "canonical": canonical}})
    source_release = {"source_id": RELEASE_SOURCE_ID, "role": "PIT-A contemporaneous release pages", "pit_a_observed": sorted(set(observed)), "pit_a_earliest": min(selected_periods) if selected_periods else None, "pit_a_latest": max(selected_periods) if selected_periods else None, "raw_manifests": release_records, "parse_failures": parse_failures, "archived_index_discovered_url_count": len(archived_index_urls), "index_reuse_only": True}
    source_data = {"source_id": DATA_SOURCE_ID, "role": "PIT-C official retrospective history", "pit_c_observed": [], "pit_c_earliest": None, "pit_c_latest": None, "raw_manifests": probe_records, "probe_failures": [item for item in probe_records if item["status"] != 200]}
    for series in (*GDP_SERIES, *INDUSTRIAL_SERIES):
        series_periods = sorted({str(row["reference_period"]) for row in rows if row["series_id"] == series})
        source_map["series"][series]["pit_a_window"] = {
            "earliest_reference_period": series_periods[0] if series_periods else None,
            "latest_reference_period": series_periods[-1] if series_periods else None,
            "observed_count": len(series_periods),
            "status": "observed_from_archived_release_raw" if series_periods else "no_archived_release_observation",
        }
        source_map["series"][series]["pit_c_window"] = {"earliest_reference_period": None, "latest_reference_period": None, "observed_count": 0, "status": "not_observed"}
    source_map["sources"][RELEASE_SOURCE_ID]["pit_a_earliest"] = min(selected_periods) if selected_periods else None
    source_map["sources"][RELEASE_SOURCE_ID]["pit_a_latest"] = max(selected_periods) if selected_periods else None
    source_map["sources"][DATA_SOURCE_ID]["pit_c_earliest"] = None
    source_map["sources"][DATA_SOURCE_ID]["pit_c_latest"] = None
    atomic_json(map_path, source_map)
    audit = build_audit(package_id="growth_output", run_mode="full", start=GDP_START, end=INDUSTRIAL_END, expected=expected, observed=observed, sources=[source_release, source_data], blockers=blockers, unexplained_missing=missing, structural_omissions=structural, raw_hashes_valid=not hash_failures, duplicate_primary_keys=duplicates, value_domain_failures=domain_failures)
    audit_validation = validate_audit(audit)
    candidate_path = output_root / "shadow" / "w1_growth_output_full_range_candidate.parquet"
    if not frame.empty and canonical["passed"]:
        write_canonical_v2_snapshot(frame, candidate_path)
    audit_path = output_root / "audits" / "w1_growth_output_full_range_audit.json"
    atomic_json(audit_path, {"audit": audit, "validation": audit_validation, "candidate": {"rows": len(frame), "path": str(candidate_path.resolve()), "research_ready": False}, "source_map": source_map})
    summary_path = output_root / "audits" / "w1_growth_output_full_range_summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("# W1 growth_output full-history candidate\n\n" + f"- Independent expected keys: {len(expected)}; GDP={len(periods['gdp'])} quarters x 2; industrial={len(periods['industrial'])} periods.\n" + f"- Observed PIT-A keys: {len(observed)}; candidate rows={len(frame)}; unexplained missing={len(missing)}.\n" + f"- Per-series observed: { {series: sum(1 for key in observed if key.startswith(series + '|')) for series in (*GDP_SERIES, *INDUSTRIAL_SERIES)} }\n" + f"- Official probes: {[(item['status'], item['url']) for item in probe_records]}; PIT-C observed=0.\n" + f"- Structural industrial omissions={len(structural)}; duplicate keys={duplicates}; domain failures={domain_failures}; raw hash failures={len(hash_failures)}.\n" + "- GDP nominal is official YTD cumulative only; no single-quarter conversion. January industrial is not synthesized; February after 2012 uses YYYY-02 with YYYY-01/02.\n" + "- Status: BLOCKED audit-only; formal curated is not written; research_ready=false.\n", encoding="utf-8")
    state_dir = output_root / "state" / "w1_growth_output_luna_full_candidate"
    state_dir.mkdir(parents=True, exist_ok=True)
    blocked_lines = [f"- {item['url']}: HTTP {item['status']}; manifest={item['manifest_path']}; sha256={item['sha256']}; error={item.get('error')}" for item in probe_records if item["status"] != 200]
    (state_dir / "BLOCKED.md").write_text("# BLOCKED: growth_output full-history candidate\n\n" + ("\n".join(blocked_lines) if blocked_lines else "- Full-range official historical coverage remains incomplete; see full audit unexplained_missing.") + "\n", encoding="utf-8")
    with (state_dir / "PROGRESS.md").open("a", encoding="utf-8") as handle:
        handle.write(f"\n- full candidate run: observed={len(observed)}/{len(expected)}, rows={len(frame)}, PIT-A={len(observed)}, PIT-C=0, unexplained_missing={len(missing)}, probe_status={[item['status'] for item in probe_records]}; formal curated unchanged and research_ready=false.\n")
    return {"audit": audit, "validation": audit_validation, "candidate": {"rows": len(frame), "path": str(candidate_path.resolve()), "research_ready": False}, "source_map": str(map_path.resolve()), "blocked": bool(blockers)}
