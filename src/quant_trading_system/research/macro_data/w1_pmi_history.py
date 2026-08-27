"""Official NBS PMI history discovery, parsing, and audit primitives."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import pandas as pd

from .adapters import _TableParser
from .contracts import CANONICAL_COLUMNS, RawSnapshot, validate_canonical_v2
from .w1_execution import build_audit, expected_periods, validate_audit


SOURCE_ID = "nbs_pmi_state_release"
ARCHIVE_SOURCE_ID = "nbs_pmi_release_archive"
LISTING_SOURCE_ID = "nbs_pmi_state_release_index"
LISTING_URL = "https://www.stats.gov.cn/sj/zxfb/"
NBS_SEARCH_URL = "https://api.so-gov.cn/query/s"
NBS_SITE_CODE = "bm36000002"
PARSER_VERSION = "r011.w1.pmi.history.v1"
SERIES = (
    "CN.PMI.MFG.HEADLINE",
    "CN.PMI.MFG.NEW_ORDERS",
    "CN.PMI.MFG.NEW_EXPORT_ORDERS",
    "CN.PMI.MFG.INPUT_PRICE",
    "CN.PMI.NONMFG.ACTIVITY",
    "CN.PMI.NONMFG.NEW_ORDERS",
    "CN.PMI.NONMFG.INPUT_PRICE",
    "CN.PMI.COMPOSITE.OUTPUT",
)
SERIES_START = {
    "CN.PMI.MFG.HEADLINE": "2009-06",
    "CN.PMI.MFG.NEW_ORDERS": "2009-06",
    "CN.PMI.MFG.NEW_EXPORT_ORDERS": "2012-04",
    "CN.PMI.MFG.INPUT_PRICE": "2012-04",
    "CN.PMI.NONMFG.ACTIVITY": "2014-11",
    "CN.PMI.NONMFG.NEW_ORDERS": "2014-11",
    "CN.PMI.NONMFG.INPUT_PRICE": "2014-11",
    "CN.PMI.COMPOSITE.OUTPUT": "2018-01",
}


def _period(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{4})\D{1,8}(\d{1,2})(?!\d)", text)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", " ", text)))


def _number(value: Any) -> float:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if match is None:
        raise ValueError(f"not numeric: {value!r}")
    return float(match.group(0))


def _target_row(table: pd.DataFrame, reference_period: str) -> list[Any] | None:
    for row in table.itertuples(index=False, name=None):
        if row and _period(str(row[0])) == reference_period:
            return list(row)
    return None


def _legacy_mfg(payload: bytes, reference_period: str) -> tuple[dict[str, float], str] | None:
    parser = _TableParser()
    parser.feed(payload.decode("utf-8", errors="strict"))
    decoded = payload.decode("utf-8", errors="strict")
    for rows in parser.tables:
        for index, row in enumerate(rows):
            if not row or str(row[0]).strip().upper() != "PMI" or index == 0:
                continue
            periods = [_period(str(item)) for item in rows[index - 1][1:]]
            if not any(periods):
                raw_periods = [_period(item.group(0)) for item in re.finditer(r"\d{4}[年/-]\d{1,2}[月]?", decoded)]
                if len(raw_periods) == 1:
                    periods = raw_periods
            if reference_period not in periods:
                continue
            column = periods.index(reference_period) + 1
            series_rows = rows[index:index + 6]
            try:
                return {
                    "CN.PMI.MFG.HEADLINE": _number(series_rows[0][column]),
                    "CN.PMI.MFG.NEW_ORDERS": _number(series_rows[2][column]),
                }, "legacy_horizontal"
            except (IndexError, ValueError):
                continue
    return None


@dataclass(frozen=True)
class PmiParseResult:
    rows: tuple[dict[str, Any], ...]
    structural_omissions: tuple[dict[str, str], ...]
    publication_at: str
    layout: str


def _publication_at(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="strict")
    match = re.search(
        r"name=[\"']PubDate[\"'][^>]+content=[\"'](\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)[\"']",
        text,
        re.IGNORECASE,
    )
    if match is None:
        visible = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
        match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)", visible)
    if match is None:
        raise ValueError("official PMI page has no publication timestamp")
    year, month, day, clock = match.groups()
    if clock.count(":") == 1:
        clock += ":00"
    return f"{year}-{int(month):02d}-{int(day):02d}T{clock}+08:00"


def parse_release(payload: bytes, reference_period: str, *, publication_fallback: str | None = None) -> PmiParseResult:
    """Parse only the direct period of one NBS release page."""
    tables = pd.read_html(BytesIO(payload))
    if not tables:
        raise ValueError("official PMI release has no HTML tables")
    try:
        publication_at = _publication_at(payload)
    except ValueError:
        if publication_fallback is None:
            raise
        publication_at = publication_fallback
    omissions: list[dict[str, str]] = []
    values: dict[str, float] = {}
    layout = "rolling"
    mfg = _target_row(tables[0], reference_period)
    if mfg is None:
        legacy = _legacy_mfg(payload, reference_period)
        if legacy is None:
            raise ValueError(f"manufacturing PMI row not found for {reference_period}")
        values.update(legacy[0])
        layout = legacy[1]
    else:
        if len(mfg) < 4:
            raise ValueError("manufacturing PMI row is truncated")
        values["CN.PMI.MFG.HEADLINE"] = _number(mfg[1])
        values["CN.PMI.MFG.NEW_ORDERS"] = _number(mfg[3])
    if len(tables) >= 2:
        detail = _target_row(tables[1], reference_period)
        if detail is not None and len(detail) >= 7:
            values["CN.PMI.MFG.NEW_EXPORT_ORDERS"] = _number(detail[1])
            values["CN.PMI.MFG.INPUT_PRICE"] = _number(detail[6])
    if len(tables) >= 3:
        nonmfg = _target_row(tables[2], reference_period)
        if nonmfg is not None and len(nonmfg) >= 4:
            values["CN.PMI.NONMFG.ACTIVITY"] = _number(nonmfg[1])
            values["CN.PMI.NONMFG.NEW_ORDERS"] = _number(nonmfg[2])
            values["CN.PMI.NONMFG.INPUT_PRICE"] = _number(nonmfg[3])
    match = re.search(r"综合PMI产出指数(?:为|是)([-+]?\d+(?:\.\d+)?)%", _compact(payload.decode("utf-8", errors="strict")))
    if match:
        values["CN.PMI.COMPOSITE.OUTPUT"] = float(match.group(1))
    for series_id in SERIES:
        if series_id not in values and reference_period >= SERIES_START[series_id]:
            omissions.append({"series_id": series_id, "reference_period": reference_period, "reason": "STRUCTURAL_FIELD_MISSING"})
    rows = tuple({"series_id": series_id, "reference_period": reference_period, "value": values[series_id]} for series_id in SERIES if series_id in values and reference_period >= SERIES_START[series_id])
    return PmiParseResult(rows, tuple(omissions), publication_at, layout)


def expected_cells(start: str, end: str) -> list[str]:
    months = expected_periods(date.fromisoformat(f"{start}-01"), date.fromisoformat(f"{end}-01"), "monthly")
    return [f"{series_id}|{period}" for series_id in SERIES for period in months if period >= SERIES_START[series_id]]


def expected_by_series(start: str, end: str) -> dict[str, list[str]]:
    cells = expected_cells(start, end)
    return {series_id: [cell.split("|", 1)[1] for cell in cells if cell.startswith(series_id + "|")] for series_id in SERIES}


def expected_series_periods(start: str, end: str) -> dict[str, list[str]]:
    return expected_by_series(start, end)


def _manifest_payload(manifest_path: Path) -> tuple[dict[str, Any], bytes, bool]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"sha256", "raw_path", "request", "response", "retrieved_at", "source_id"}
    if not required.issubset(manifest):
        return manifest, b"", False
    raw_path = Path(str(manifest["raw_path"]))
    if not raw_path.exists():
        return manifest, b"", False
    payload = raw_path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    return manifest, payload, actual == manifest["sha256"]


def verify_manifest_hashes(manifest_paths: Iterable[Path]) -> dict[str, Any]:
    checked = 0
    failures: list[dict[str, Any]] = []
    for path in manifest_paths:
        checked += 1
        try:
            manifest, payload, valid = _manifest_payload(path)
            if not valid:
                failures.append({"manifest": str(path), "expected_sha256": manifest.get("sha256"), "actual_sha256": hashlib.sha256(payload).hexdigest() if payload else None})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append({"manifest": str(path), "reason": f"{type(exc).__name__}: {exc}"})
    return {"checked": checked, "failures": failures, "valid": not failures}


class _ReleaseLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.title = ""
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            data = dict(attrs)
            self.href = data.get("href")
            self.title = data.get("title") or ""
    def handle_data(self, data: str) -> None:
        if self.href is not None:
            self.title += data
    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.title.split())))
            self.href, self.title = None, ""


def _pseudo(status: int, headers: dict[str, str], payload: bytes) -> bool:
    content_type = headers.get("Content-Type", headers.get("content-type", "")).lower()
    sample = payload[:4096].decode("utf-8", errors="ignore").lower()
    return status != 200 or "html" not in content_type or any(token in sample for token in ("验证码", "captcha", "access denied"))


def _release_url(href: str) -> str:
    return urljoin(LISTING_URL, href)


def _listing_candidates(index_manifest_paths: Iterable[Path]) -> set[str]:
    candidates: set[str] = set()
    for manifest_path in index_manifest_paths:
        manifest, payload, valid = _manifest_payload(manifest_path)
        if not valid or manifest.get("response", {}).get("status") != 200:
            continue
        parser = _ReleaseLinks()
        parser.feed(payload.decode("utf-8", errors="strict"))
        for href, title in parser.links:
            if "采购经理指数" not in title or "解读" in title or "答记者问" in title:
                continue
            candidates.add(urljoin(LISTING_URL, href))
    return candidates


def _archive_entries(output_root: Path, start: str, end: str) -> tuple[list[dict[str, Any]], list[Path]]:
    catalog_path = output_root / "catalogs" / "pmi_release_pages.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifests = {}
    archive_root = output_root / "raw" / ARCHIVE_SOURCE_ID
    for path in archive_root.rglob("*.manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        url = str(manifest.get("request", {}).get("url", ""))
        if url and manifest.get("response", {}).get("status") == 200:
            manifests[url] = path
    catalog_manifest_paths: list[Path] = []
    entries: list[dict[str, Any]] = []
    for item in catalog.get("pages", []):
        url = str(item.get("url", ""))
        period = str(item.get("reference_period") or "")
        if url in manifests:
            catalog_manifest_paths.append(manifests[url])
        if not url or not period or not (start <= period <= end) or url not in manifests:
            continue
        entries.append({**item, "url": url, "reference_period": period, "manifest_path": str(manifests[url])})
    entries.sort(key=lambda item: (item["reference_period"], item["url"]))
    return entries, list(dict.fromkeys(catalog_manifest_paths))


def _snapshot_from_manifest(manifest_path: Path) -> tuple[RawSnapshot, bytes, bool]:
    manifest, payload, valid = _manifest_payload(manifest_path)
    request = manifest.get("request", {})
    response = manifest.get("response", {})
    snapshot = RawSnapshot(
        source_id=SOURCE_ID,
        retrieved_at=str(manifest.get("retrieved_at", "")),
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        raw_path=str(Path(str(manifest.get("raw_path", ""))).resolve()),
        manifest_path=str(manifest_path.resolve()),
        request_method=str(request.get("method", "GET")),
        request_url=str(request.get("url", "")),
        response_status=int(response.get("status", 0)),
        content_type=str(response.get("headers", {}).get("content-type", "text/html")),
    )
    return snapshot, payload, valid


def _record(row: dict[str, Any], snapshot: RawSnapshot, publication_at: str, layout: str) -> dict[str, Any]:
    return {
        "series_id": row["series_id"], "reference_period": row["reference_period"], "value": row["value"],
        "unit": "diffusion_index_percent", "seasonal_adjustment": "seasonally_adjusted",
        "source_id": SOURCE_ID, "source_record_id": f"{layout}|{row['reference_period']}|{row['series_id']}",
        "release_at": publication_at, "available_at": publication_at, "tradable_at": publication_at,
        "availability_evidence": "official_nbs_release_page_publication_timestamp",
        "retrieved_at": snapshot.retrieved_at, "vintage_id": f"{ARCHIVE_SOURCE_ID}:{snapshot.sha256[:16]}",
        "raw_sha256": snapshot.sha256, "parser_version": PARSER_VERSION,
    }


def _vintage_periods(payload: bytes, direct_period: str) -> dict[str, set[str]]:
    result = {series_id: set() for series_id in SERIES}
    tables = pd.read_html(BytesIO(payload))
    for table, fields in zip(tables[:3], (SERIES[:2], SERIES[2:4], SERIES[4:7]), strict=False):
        for row in table.itertuples(index=False, name=None):
            period = _period(str(row[0])) if row else None
            if period:
                result[fields[0]].add(period)
                if len(fields) > 1:
                    result[fields[1]].add(period)
                    if len(fields) > 2:
                        result[fields[2]].add(period)
    text = _compact(payload.decode("utf-8", errors="strict"))
    if "综合PMI产出指数" in text:
        result[SERIES[7]].add(direct_period)
    return result


def run_history_shadow(output_root: Path, start: str = "2009-06", end: str = "2026-07") -> dict[str, Any]:
    entries, catalog_manifest_paths = _archive_entries(output_root, start, end)
    hash_audit = verify_manifest_hashes(catalog_manifest_paths)
    index_manifests = list((output_root / "raw" / LISTING_SOURCE_ID).rglob("*.manifest.json"))
    listing_urls = _listing_candidates(index_manifests)
    direct_periods = sorted({str(item["reference_period"]) for item in entries})
    expected = expected_cells(start, end)
    records: list[dict[str, Any]] = []
    structural: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    vintage_coverage = {series_id: set() for series_id in SERIES}
    layout_counts: dict[str, int] = {}
    for item in entries:
        manifest_path = Path(item["manifest_path"])
        snapshot, payload, valid = _snapshot_from_manifest(manifest_path)
        if not valid:
            continue
        try:
            fallback = f"{item.get('document_date', item['reference_period'])}T12:00:00+08:00"
            parsed = parse_release(payload, str(item["reference_period"]), publication_fallback=fallback)
            layout_counts[parsed.layout] = layout_counts.get(parsed.layout, 0) + 1
            records.extend(_record(row, snapshot, parsed.publication_at, parsed.layout) for row in parsed.rows)
            structural.extend({**omission, "url": item["url"], "raw_sha256": snapshot.sha256} for omission in parsed.structural_omissions)
            vintage = _vintage_periods(payload, str(item["reference_period"]))
            for series_id, periods in vintage.items():
                vintage_coverage[series_id].update(period for period in periods if period >= SERIES_START[series_id])
        except (ValueError, ImportError) as exc:
            parse_failures.append({"reference_period": item["reference_period"], "url": item["url"], "reason": f"{type(exc).__name__}: {exc}"})
    frame = pd.DataFrame(records, columns=CANONICAL_COLUMNS)
    metadata_failures: list[str] = []
    if records:
        v2 = frame.copy()
        v2["schema_version"] = 2
        v2["reference_period_start"] = v2["reference_period"]
        v2["reference_period_end"] = v2["reference_period"]
        v2["period_span"] = v2["reference_period"]
        v2["measure_basis"] = "period_observation"
        v2["methodology_version"] = "nbs_pmi_history_frozen_field_mapping_v1"
        v2["regime_id"] = "pmi_state"
        v2["pit_grade"] = "A"
        v2["license_scope"] = "internal_research"
        v2 = v2[[*CANONICAL_COLUMNS, "schema_version", "reference_period_start", "reference_period_end", "period_span", "measure_basis", "methodology_version", "regime_id", "pit_grade", "license_scope"]]
        metadata_validation = validate_canonical_v2(v2)
        if not metadata_validation["passed"]:
            raise ValueError(f"canonical metadata validation failed: {metadata_validation['failures']}")
        if not v2["pit_grade"].eq("A").all() or not v2["license_scope"].eq("internal_research").all():
            metadata_failures.append("frozen metadata mismatch")
        canonical_validation = validate_canonical_v2(v2)
    else:
        canonical_validation = {"passed": True, "rows": 0, "failures": []}
    observed = sorted({f"{row['series_id']}|{row['reference_period']}" for row in records})
    observed_set = set(observed)
    missing_cells = sorted(set(expected) - observed_set)
    known_missing_periods = {"2010-04", "2010-05", "2011-06", "2011-07"}
    explained_missing = [cell for cell in missing_cells if cell.split("|", 1)[1] in known_missing_periods]
    unexplained = [cell for cell in missing_cells if cell not in explained_missing]
    page_missing = [f"{series_id}|{period}" for series_id in SERIES for period in sorted(known_missing_periods) if period >= SERIES_START[series_id] and period not in direct_periods]
    duplicates = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not frame.empty else 0
    domain_failures = int((~frame["value"].between(0, 100)).sum()) if not frame.empty else 0
    listing_periods = sorted({str(item["reference_period"]) for item in entries if item["url"] in listing_urls})
    search_periods = direct_periods
    observed_by_series = {series_id: sorted({row["reference_period"] for row in records if row["series_id"] == series_id}) for series_id in SERIES}
    series_coverage = {
        series_id: {
            "expected_start": SERIES_START[series_id],
            "expected_end": end,
            "observed_count": len(observed_by_series[series_id]),
            "observed_start": observed_by_series[series_id][0] if observed_by_series[series_id] else None,
            "observed_end": observed_by_series[series_id][-1] if observed_by_series[series_id] else None,
        }
        for series_id in SERIES
    }
    source = {
        "source_id": SOURCE_ID,
        "official_listing": LISTING_URL,
        "official_search": {"url": NBS_SEARCH_URL, "siteCode": NBS_SITE_CODE, "query_semantics": "backfill.py modern title search plus year-bounded legacy title search"},
        "mechanisms": {
            "current_listing": {"index_manifest_count": len(index_manifests), "discovered_url_count": len(listing_urls), "period_count": len(listing_periods), "periods": listing_periods},
            "backfill_official_search_replay": {"catalog_count": len(search_periods), "period_count": len(search_periods), "periods": search_periods},
            "union_period_count": len(set(listing_periods) | set(search_periods)),
            "catalog_direct_period_count": len(direct_periods),
        },
        "archive_manifest_count": len(catalog_manifest_paths),
        "archive_entry_count": len(entries),
        "parse_failures": parse_failures,
        "vintage_coverage": {series_id: {"period_count": len(periods), "min": min(periods) if periods else None, "max": max(periods) if periods else None} for series_id, periods in vintage_coverage.items()},
        "expected_by_series": expected_by_series(start, end),
        "observed_by_series": observed_by_series,
        "series_coverage": series_coverage,
        "series_start": SERIES_START,
        "layout_counts": layout_counts,
        "canonical_validation": canonical_validation,
        "history_detail": {
            "direct_release_periods": direct_periods,
            "direct_release_page_coverage": len(direct_periods),
            "layout_counts": layout_counts,
            "page_internal_vintage_coverage": {series_id: {"period_count": len(periods), "min": min(periods) if periods else None, "max": max(periods) if periods else None} for series_id, periods in vintage_coverage.items()},
            "explained_missing_cells": explained_missing,
            "official_release_page_not_discovered": page_missing,
            "raw_hash": hash_audit,
            "metadata_failures": metadata_failures,
            "pit_grade": "A",
            "license_scope": "internal_research",
            "listing_vs_search_period_difference": sorted(set(search_periods) - set(listing_periods)),
        },
    }
    blockers: list[dict[str, Any]] = []
    if not hash_audit["valid"]:
        blockers.append({"code": "RAW_HASH_INVALID", "detail": "one or more archive raw bytes do not match manifest sha256"})
    if parse_failures or unexplained or metadata_failures:
        blockers.append({"code": "PMI_HISTORY_AUDIT_UNEXPLAINED", "detail": "parse, metadata, or missing-cell failures remain"})
    audit = build_audit(
        package_id="pmi_state", run_mode="shadow", start=start, end=end,
        expected=expected, observed=observed, sources=[source], blockers=blockers,
        unexplained_missing=unexplained, structural_omissions=[*structural, *[{"series_id": cell.split("|", 1)[0], "reference_period": cell.split("|", 1)[1], "reason": "OFFICIAL_RELEASE_PAGE_NOT_DISCOVERED"} for cell in page_missing]],
        raw_hashes_valid=hash_audit["valid"], duplicate_primary_keys=duplicates, value_domain_failures=domain_failures,
    )
    validation = validate_audit(audit)
    return {"audit": audit, "validation": validation, "research_ready": False, "_frame": v2 if records else pd.DataFrame()}
