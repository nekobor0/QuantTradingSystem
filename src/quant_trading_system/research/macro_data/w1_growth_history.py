"""Bounded, official NBS history discovery and parsing for W1 growth output."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException, IncompleteRead
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import pandas as pd

from .contracts import CANONICAL_COLUMNS, CANONICAL_V2_COLUMNS, validate_canonical_v2
from .w1_execution import build_audit, validate_audit


SOURCE_ID = "NBS_RELEASE"
RAW_SOURCE_ID = "nbs_growth_output_official"
PARSER_VERSION = "w1_growth_output_bounded_v1"
METHODOLOGY_VERSION = "nbs_growth_output_official_release_v1"
INDEX_URL = "https://www.stats.gov.cn/sj/zxfb/index.html"
INDEX_MAX_PAGES = 80
GDP_SERIES = ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY")
INDUSTRIAL_SERIES = ("CN.INDUSTRIAL.VA.YOY",)

# URLs discovered through the official NBS page-search mechanism. These are
# page identities only; values still come exclusively from archived HTML.
DIRECT_RELEASE_SEEDS = (
    "https://www.stats.gov.cn/sj/zxfb/202410/t20241019_1957083.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202501/t20250118_1958363.html",
    "https://www.stats.gov.cn/sj/zxfb/202504/t20250416_1959321.html",
    "https://www.stats.gov.cn/sj/zxfb/202601/t20260120_1962349.html",
    "https://www.stats.gov.cn/sj/zxfb/202409/t20240914_1956486.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202410/t20241018_1957043.html",
    "https://www.stats.gov.cn/sj/zxfb/202411/t20241115_1957430.html",
    "https://www.stats.gov.cn/sj/zxfb/202412/t20241216_1957765.html",
    "https://www.stats.gov.cn/sj/zxfb/202501/t20250117_1958331.html",
    "https://www.stats.gov.cn/sj/zxfb/202503/t20250317_1959012.html",
    "https://www.stats.gov.cn/sj/zxfb/202504/t20250416_1959320.html",
    "https://www.stats.gov.cn/sj/zxfb/202510/t20251020_1961611.html",
    "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
)


@dataclass(frozen=True)
class ParsedRelease:
    kind: str
    period: str
    publication_at: str
    publication_original: str
    rows: tuple[dict[str, Any], ...]
    layout: str


def _decode(payload: bytes) -> str:
    return payload.decode("utf-8", errors="strict")


def _visible_text(payload: bytes) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", _decode(payload)))
    return " ".join(text.split())


def _title(payload: bytes) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", _decode(payload), re.I | re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split()) if match else ""


def _tables(payload: bytes) -> list[pd.DataFrame]:
    return pd.read_html(StringIO(_decode(payload)))


def _number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text or text.lower() == "nan" or text in {"…", "...", "--", "－"}:
        return None
    match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _row_numbers(row: Iterable[Any]) -> list[float]:
    return [number for number in (_number(value) for value in row) if number is not None]


def _quarter_in_text(text: str) -> str | None:
    match = re.search(r"(20\d{2})\s*年\s*([一二三四1234])\s*(?:季度|季)", text)
    if match is None:
        return None
    quarter = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(match.group(2), match.group(2))
    return f"{match.group(1)}-Q{quarter}"


def _industrial_period_in_text(text: str) -> str | None:
    cumulative = re.search(r"(20\d{2})\s*年\s*1\s*[—－-]\s*(\d{1,2})\s*月份", text)
    if cumulative:
        return f"{cumulative.group(1)}-{int(cumulative.group(2)):02d}"
    regular = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月份", text)
    if regular:
        return f"{regular.group(1)}-{int(regular.group(2)):02d}"
    return None


def _publication(payload: bytes) -> tuple[str, str]:
    raw = _decode(payload)
    patterns = (
        r"20\d{2}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?",
        r"20\d{2}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}(?::\d{2})?",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            original = match.group(0)
            normalized = re.sub(r"年|月", "-", original.replace("日", " ").replace("/", "-"))
            parsed = datetime.strptime(normalized.strip(), "%Y-%m-%d %H:%M:%S" if normalized.count(":") == 2 else "%Y-%m-%d %H:%M")
            return original, parsed.replace(tzinfo=_SHANGHAI).isoformat()
    raise ValueError("official page has no publication date and time evidence")


try:
    from zoneinfo import ZoneInfo

    _SHANGHAI = ZoneInfo("Asia/Shanghai")
except ImportError:  # pragma: no cover - supported Python versions provide zoneinfo
    _SHANGHAI = timezone.utc


def parse_gdp_release(payload: bytes, quarter: str) -> ParsedRelease:
    if not re.fullmatch(r"20\d{2}-Q[1-4]", quarter):
        raise ValueError(f"invalid GDP quarter: {quarter}")
    text = _visible_text(payload)
    if _quarter_in_text((_title(payload) + " " + text)) != quarter:
        raise ValueError(f"GDP page period does not match {quarter}")
    gdp_row: list[Any] | None = None
    layout = ""
    for index, table in enumerate(_tables(payload)):
        for _, row in table.iterrows():
            cells = row.tolist()
            labels = " ".join(str(cell) for cell in cells[:2])
            if str(cells[0]).strip() == "GDP" or "国内生产总值" in labels:
                gdp_row = cells
                layout = f"gdp_table_{index}"
                break
        if gdp_row is not None:
            break
    if gdp_row is None:
        raise ValueError("GDP release has no GDP row")
    numbers = _row_numbers(gdp_row[1:])
    if len(numbers) >= 4:
        nominal_ytd, real_yoy = numbers[1], numbers[2]
    elif len(numbers) >= 2:
        nominal_ytd, real_yoy = numbers[0], numbers[1]
    else:
        raise ValueError("GDP row does not expose YTD amount and real YoY")
    publication_original, publication_at = _publication(payload)
    return ParsedRelease(
        "gdp", quarter, publication_at, publication_original,
        (
            {"series_id": "CN.GDP.NOMINAL.YTD", "reference_period": quarter, "value": nominal_ytd, "unit": "100m_cny", "measure_basis": "ytd_cumulative", "period_span": quarter},
            {"series_id": "CN.GDP.REAL.YOY", "reference_period": quarter, "value": real_yoy, "unit": "percent_yoy", "measure_basis": "period_observation", "period_span": quarter},
        ),
        layout,
    )


def parse_industrial_release(payload: bytes, period: str) -> ParsedRelease:
    if not re.fullmatch(r"20\d{2}-\d{2}", period):
        raise ValueError(f"invalid industrial period: {period}")
    context = _title(payload) + " " + _visible_text(payload)
    if _industrial_period_in_text(context) != period:
        raise ValueError(f"industrial page period does not match {period}")
    value: float | None = None
    layout = ""
    for index, table in enumerate(_tables(payload)):
        for _, row in table.iterrows():
            cells = row.tolist()
            label = str(cells[0]).replace(" ", "") if cells else ""
            if "规模以上工业增加值" in label:
                numbers = _row_numbers(cells[1:])
                if numbers:
                    value, layout = numbers[0], f"industrial_table_{index}"
                    break
        if value is not None:
            break
    if value is None:
        raise ValueError("industrial release has no scale-above industrial value row")
    publication_original, publication_at = _publication(payload)
    span = f"{period[:4]}-01/02" if period.endswith("-02") and re.search(r"1\s*[—－-]\s*2\s*月份", context) else period
    return ParsedRelease(
        "industrial", period, publication_at, publication_original,
        ({"series_id": "CN.INDUSTRIAL.VA.YOY", "reference_period": period, "value": value, "unit": "percent_yoy", "measure_basis": "period_observation", "period_span": span},),
        layout,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".growth-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _capture(
    output_root: Path,
    *,
    source_type: str,
    url: str,
    status: int,
    headers: dict[str, str],
    payload: bytes,
    discovery_mechanism: str,
    publication_original: str | None,
) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    root = output_root / "raw" / RAW_SOURCE_ID / source_type / digest[:2]
    raw_path = root / f"{digest}.html"
    if raw_path.exists() and raw_path.read_bytes() != payload:
        raise RuntimeError(f"immutable raw collision: {raw_path}")
    if not raw_path.exists():
        _atomic_write(raw_path, payload)
    captured = datetime.now(timezone.utc)
    manifest = {
        "schema_version": 1,
        "source_id": SOURCE_ID,
        "source_type": source_type,
        "retrieved_at": captured.isoformat(),
        "sha256": digest,
        "bytes": len(payload),
        "raw_path": str(raw_path.resolve()),
        "request": {"method": "GET", "url": url},
        "response": {"status": status, "headers": {key.lower(): value for key, value in headers.items() if key.lower() in {"content-type", "date", "etag", "last-modified"}}},
        "discovery_mechanism": discovery_mechanism,
        "page_publication_time_original": publication_original,
    }
    manifest_path = root / f"{digest}.{captured.strftime('%Y%m%dT%H%M%S%fZ')}.manifest.json"
    _atomic_write(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {"manifest": manifest, "manifest_path": str(manifest_path.resolve()), "raw_path": str(raw_path.resolve())}


def _fetch(url: str, fetcher: Callable[[str], tuple[int, dict[str, str], bytes, str | None]] | None = None) -> tuple[int, dict[str, str], bytes, str | None]:
    if fetcher is not None:
        return fetcher(url)
    request = Request(url, headers={"User-Agent": "QuantTradingSystem-W1-growth/1.0", "Accept": "text/html"})
    last_error: str | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                return int(response.status), dict(response.headers.items()), response.read(), None
        except HTTPError as exc:
            body = exc.read()
            last_error = f"HTTPError: {exc.code}"
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == 2:
                return int(exc.code), dict(exc.headers.items()), body, last_error
        except (URLError, TimeoutError, OSError, HTTPException, IncompleteRead) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 2:
                return 0, {}, b"", last_error
    return 0, {}, b"", last_error or "official fetch failed"


def _links(payload: bytes) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    pattern = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
    for href, label in pattern.findall(_decode(payload)):
        url = urljoin(INDEX_URL, html.unescape(href).strip())
        parts = urlsplit(url)
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", label)).split())
        if parts.netloc.lower() not in {"www.stats.gov.cn", "stats.gov.cn"}:
            continue
        if "/sj/zxfb/" not in parts.path and "/sj/zxfbhjd/" not in parts.path:
            continue
        if parts.path.endswith("index.html") or not parts.path.endswith(".html"):
            continue
        result.append({"url": url, "title": text})
    unique: dict[str, dict[str, str]] = {}
    for item in result:
        unique.setdefault(item["url"], item)
    return list(unique.values())


def _index_url(page: int) -> str:
    return INDEX_URL if page == 0 else INDEX_URL.replace("index.html", f"index_{page}.html")


def _expected(start: str, end: str) -> tuple[list[str], list[str], list[str]]:
    if (start, end) != ("2024-08", "2026-07"):
        raise ValueError("bounded growth candidate is frozen to 2024-08—2026-07")
    gdp = ["2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"]
    industrial = ["2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    cells = [f"{series}|{period}" for period in gdp for series in GDP_SERIES] + [f"CN.INDUSTRIAL.VA.YOY|{period}" for period in industrial]
    return gdp, industrial, cells


def _row(record: dict[str, Any], parsed: ParsedRelease, manifest: dict[str, Any], url: str) -> dict[str, Any]:
    period = str(record["reference_period"])
    if parsed.kind == "gdp":
        start = end = period
    elif period.endswith("-02") and str(record["period_span"]).endswith("01/02"):
        start, end = f"{period[:4]}-01", period
    else:
        start = end = period
    raw_sha = str(manifest["sha256"])
    series_id = str(record["series_id"])
    return {
        "series_id": series_id, "reference_period": period, "value": float(record["value"]), "unit": record["unit"],
        "seasonal_adjustment": "not_applicable", "source_id": SOURCE_ID,
        "source_record_id": f"{SOURCE_ID}:{hashlib.sha256(url.encode()).hexdigest()[:16]}:{series_id}",
        "release_at": parsed.publication_at, "available_at": parsed.publication_at, "tradable_at": parsed.publication_at,
        "availability_evidence": f"official NBS release page publication timestamp: {parsed.publication_original}",
        "retrieved_at": str(manifest["retrieved_at"]),
        "vintage_id": f"nbs_growth_release:{parsed.kind}:{period}:{raw_sha[:16]}", "raw_sha256": raw_sha,
        "parser_version": PARSER_VERSION, "schema_version": 2, "reference_period_start": start,
        "reference_period_end": end, "period_span": record["period_span"], "measure_basis": record["measure_basis"],
        "methodology_version": METHODOLOGY_VERSION, "regime_id": "growth_output_bounded",
        "pit_grade": "A", "license_scope": "internal_research",
    }


def _manifest_hash_audit(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for item in manifests:
        path = Path(str(item["manifest_path"]))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            raw = Path(str(manifest["raw_path"]))
            if hashlib.sha256(raw.read_bytes()).hexdigest() != manifest.get("sha256"):
                failures.append(str(path))
        except (OSError, ValueError, KeyError, TypeError):
            failures.append(str(path))
    return {"checked": len(manifests), "failures": failures, "valid": not failures}


def _archived_release_items(output_root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for manifest_path in sorted((output_root / "raw" / RAW_SOURCE_ID / "release").rglob("*.manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            url = str(manifest["request"]["url"])
            raw_path = Path(str(manifest["raw_path"]))
            digest = str(manifest["sha256"])
            if not raw_path.exists() or (url, digest) in seen:
                continue
            seen.add((url, digest))
            payload = raw_path.read_bytes()
            items.append({"url": url, "title": _title(payload), "archived_manifest": manifest})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return items


def run_bounded_candidate(
    output_root: Path,
    start: str = "2024-08",
    end: str = "2026-07",
    *,
    fetcher: Callable[[str], tuple[int, dict[str, str], bytes, str | None]] | None = None,
    discovery: str = "combined",
) -> dict[str, Any]:
    if discovery not in {"combined", "index", "direct-search"}:
        raise ValueError(f"unsupported discovery mechanism: {discovery}")
    gdp_expected, industrial_expected, expected_cells = _expected(start, end)
    index_records: list[dict[str, Any]] = []
    index_failures: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    if discovery in {"combined", "index"}:
        for page in range(INDEX_MAX_PAGES):
            url = _index_url(page)
            status, headers, payload, error = _fetch(url, fetcher)
            publication_original = None
            try:
                publication_original, _ = _publication(payload) if payload else (None, None)
            except ValueError:
                pass
            if payload or status:
                capture = _capture(output_root, source_type="index", url=url, status=status, headers=headers, payload=payload, discovery_mechanism="official_stats_release_index_pagination", publication_original=publication_original)
                index_records.append({"url": url, "status": status, "manifest_path": capture["manifest_path"], "sha256": capture["manifest"]["sha256"], "bytes": len(payload), "error": error})
            if status != 200:
                if page == 0 or status not in {404, 410}:
                    index_failures.append({"url": url, "status": status, "error": error})
                break
            page_links = _links(payload)
            links.extend(page_links)
            if not page_links:
                break
    unique_links: dict[str, dict[str, str]] = {}
    for item in links:
        text = item["title"]
        if ("国内生产总值" in text and "季度" in text) or "规模以上工业增加值" in text:
            unique_links.setdefault(item["url"], item)
    for item in _archived_release_items(output_root):
        unique_links.setdefault(item["url"], item)  # type: ignore[arg-type]
    if discovery in {"combined", "direct-search"}:
        for url in DIRECT_RELEASE_SEEDS:
            unique_links.setdefault(url, {"url": url, "title": ""})
    release_records: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    fetch_failures: list[dict[str, Any]] = []
    duplicate_pages: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    selected_periods: set[str] = set()
    observed_by_series: dict[str, set[str]] = {series: set() for series in (*GDP_SERIES, *INDUSTRIAL_SERIES)}
    period_audit: dict[str, dict[str, Any]] = {period: {"kind": "gdp", "url": None, "status": None, "missing_series": list(GDP_SERIES)} for period in gdp_expected}
    period_audit.update({period: {"kind": "industrial", "url": None, "status": None, "missing_series": list(INDUSTRIAL_SERIES)} for period in industrial_expected})
    for item in unique_links.values():
        url = item["url"]
        archived_manifest = item.get("archived_manifest")
        if archived_manifest is not None:
            manifest = archived_manifest
            payload = Path(str(manifest["raw_path"])).read_bytes()
            status = int(manifest["response"]["status"])
            headers = {}
            error = None
            capture = {"manifest": manifest, "manifest_path": str(next((path for path in (output_root / "raw" / RAW_SOURCE_ID / "release").rglob(f"{manifest['sha256']}.*.manifest.json")), "")), "raw_path": str(manifest["raw_path"])}
        else:
            status, headers, payload, error = _fetch(url, fetcher)
            capture = None
        publication_original = None
        try:
            publication_original, _ = _publication(payload) if payload else (None, None)
        except ValueError:
            pass
        if not payload and not status:
            fetch_failures.append({"url": url, "status": status, "error": error})
            continue
        if capture is None:
            capture = _capture(output_root, source_type="release", url=url, status=status, headers=headers, payload=payload, discovery_mechanism="official_stats_release_index_pagination" if item["title"] else "official_stats_release_page_search", publication_original=publication_original)
        release_records.append({"url": url, "status": status, "manifest_path": capture["manifest_path"], "sha256": capture["manifest"]["sha256"], "bytes": len(payload), "title": item["title"], "error": error})
        if status != 200:
            fetch_failures.append({"url": url, "status": status, "error": error})
            continue
        try:
            context = item["title"] + " " + _visible_text(payload)
            quarter = _quarter_in_text(context)
            industrial_period = _industrial_period_in_text(context)
            if quarter in gdp_expected:
                parsed = parse_gdp_release(payload, quarter)
                target_key = quarter
            elif industrial_period in industrial_expected:
                parsed = parse_industrial_release(payload, industrial_period)
                target_key = industrial_period
            else:
                continue
            if target_key in selected_periods:
                duplicate_pages.append({"period": target_key, "url": url, "selected_url": str(period_audit[target_key]["url"])})
                continue
            selected_periods.add(target_key)
            period_audit[target_key].update({"url": url, "status": status, "manifest_path": capture["manifest_path"], "sha256": capture["manifest"]["sha256"], "publication_time_original": parsed.publication_original, "layout": parsed.layout})
            for record in parsed.rows:
                rows.append(_row(record, parsed, capture["manifest"], url))
                observed_by_series[str(record["series_id"])].add(str(record["reference_period"]))
                period_audit[target_key]["missing_series"] = [series for series in period_audit[target_key]["missing_series"] if series != record["series_id"]]
        except (ValueError, IndexError, ImportError) as exc:
            parse_failures.append({"url": url, "title": item["title"], "error": f"{type(exc).__name__}: {exc}"})
    frame = pd.DataFrame(rows, columns=CANONICAL_V2_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["reference_period", "series_id", "vintage_id"], kind="mergesort").reset_index(drop=True)
    duplicates = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not frame.empty else 0
    domain_failures = int((~frame["value"].between(-100.0, 2_000_000.0)).sum()) if not frame.empty else 0
    expected_by_series = {series: [f"{series}|{period}" for period in gdp_expected] for series in GDP_SERIES}
    expected_by_series["CN.INDUSTRIAL.VA.YOY"] = [f"CN.INDUSTRIAL.VA.YOY|{period}" for period in industrial_expected]
    observed_cells = sorted({f"{row['series_id']}|{row['reference_period']}" for row in rows})
    missing_cells = sorted(set(expected_cells) - set(observed_cells))
    raw_audit = _manifest_hash_audit(index_records + release_records)
    canonical = validate_canonical_v2(frame) if not frame.empty else {"passed": False, "failures": ["empty_frame"], "rows": 0}
    source = {
        "source_id": SOURCE_ID, "authority": "official NBS stats.gov.cn", "license_scope": "internal_research",
        "discovery_mechanism": {
            "combined": "official_stats_release_index_pagination+official_stats_release_page_search",
            "index": "official_stats_release_index_pagination",
            "direct-search": "official_stats_release_page_search",
        }[discovery], "index_pages": index_records,
        "index_failures": index_failures, "release_pages": release_records, "parse_failures": parse_failures,
        "fetch_failures": fetch_failures, "duplicate_pages": duplicate_pages, "period_audit": period_audit, "expected_by_series": expected_by_series,
        "observed_by_series": {key: sorted(value) for key, value in observed_by_series.items()},
        "raw_manifests": index_records + release_records, "raw_hash": raw_audit,
        "publication_pit_evidence": {period: period_audit[period].get("publication_time_original") for period in period_audit if period_audit[period].get("publication_time_original")},
        "canonical_v2": canonical, "row_count": len(frame), "gdp_quarter_count": len(gdp_expected), "industrial_period_count": len(industrial_expected),
        "jan_feb_policy": "reference_period=YYYY-02 and period_span=YYYY-01/02; January is never synthesized",
    }
    blockers: list[dict[str, Any]] = []
    if index_failures:
        blockers.append({"code": "LISTING_QUARANTINED", "detail": index_failures})
    if parse_failures or fetch_failures or missing_cells:
        blockers.append({"code": "OFFICIAL_COVERAGE_INCOMPLETE", "detail": {"parse_failures": parse_failures, "fetch_failures": fetch_failures, "unexplained_missing": missing_cells}})
    if not raw_audit["valid"]:
        blockers.append({"code": "RAW_HASH_INVALID", "detail": raw_audit["failures"]})
    if duplicates or domain_failures or not canonical["passed"]:
        blockers.append({"code": "CANONICAL_V2_INVALID", "detail": {"duplicate_primary_keys": duplicates, "value_domain_failures": domain_failures, "canonical": canonical}})
    audit = build_audit(package_id="growth_output", run_mode="shadow", start=start, end=end, expected=expected_cells, observed=observed_cells, sources=[source], blockers=blockers, unexplained_missing=missing_cells, structural_omissions=[], raw_hashes_valid=raw_audit["valid"], duplicate_primary_keys=duplicates, value_domain_failures=domain_failures)
    validation = validate_audit(audit)
    shadow = output_root / "shadow" / "w1_growth_output_bounded_candidate.parquet"
    if not frame.empty and canonical["passed"]:
        from .contracts import write_canonical_v2_snapshot

        write_canonical_v2_snapshot(frame, shadow)
    audit_path = output_root / "audits" / "w1_growth_output_bounded_candidate.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"audit": audit, "validation": validation, "candidate": {"rows": len(frame), "path": str(shadow), "research_ready": False}}
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary = output_root / "audits" / "w1_growth_output_bounded_candidate_summary.md"
    summary.write_text(
        "# W1 growth_output bounded official candidate\n\n"
        f"- Window: {start}—{end}; GDP quarters={len(gdp_expected)}; industrial periods={len(industrial_expected)}; expected cells=38.\n"
        f"- Observed cells: {len(observed_cells)}/38; rows={len(frame)}; raw manifests={raw_audit['checked']}; raw hash valid={raw_audit['valid']}.\n"
        f"- Duplicate keys={duplicates}; value-domain failures={domain_failures}; parse failures={len(parse_failures)}; fetch failures={len(fetch_failures)}; unexplained missing={len(missing_cells)}.\n"
        "- GDP nominal is YTD cumulative; Jan-Feb industrial data uses reference_period=YYYY-02 and explicit period_span=YYYY-01/02.\n"
        "- Source: official NBS release pages; license_scope=internal_research; research_ready=false; formal curated is not written.\n",
        encoding="utf-8",
    )
    return {"audit": audit, "validation": validation, "candidate": {"rows": len(frame), "path": str(shadow), "research_ready": False}, "blocked": audit["blocked"]}
