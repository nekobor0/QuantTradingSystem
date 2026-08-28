"""Official NBS CPI/PPI history discovery, parsing, and audit-only shadowing."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from calendar import monthrange
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from quant_trading_system.research.macro_data.contracts import CANONICAL_V2_COLUMNS, validate_canonical_v2
from quant_trading_system.research.macro_data.w1_execution import build_audit, expected_periods, validate_audit


SERIES = (
    "CN.CPI.ALL.YOY",
    "CN.CPI.CORE.YOY",
    "CN.PPI.ALL.YOY",
    "CN.PPI.ALL.MOM",
    "CN.PPIRM.ALL.YOY",
)
SOURCE_ID = "nbs_prices_official_release"
SEARCH_SOURCE_ID = "nbs_prices_official_search"
LISTING_SOURCE_ID = "nbs_prices_official_listing"
METHODOLOGY_SOURCE_ID = "nbs_prices_official_methodology"
SEARCH_URL = "https://api.so-gov.cn/query/s"
SITE_CODE = "bm36000002"
LISTING_URLS = (
    "https://www.stats.gov.cn/sj/zxfb/",
    "https://www.stats.gov.cn/sj/sjjd/",
)
USER_AGENT = "QuantTradingSystem-R011-internal-research/1.0"
QUERY_TERMS = {
    "cpi": "居民消费价格同比",
    "ppi": "工业生产者出厂价格同比",
    "interpretation": "CPI PPI 解读",
    "methodology": "基期轮换 CPI PPI",
}
PARSER_VERSION = "nbs_prices_history_v1"
METHODOLOGY_VERSION = "nbs_prices_base_year_regime_v1"
METHODOLOGY_SEED_URLS = (
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900992.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901185.html",
    "https://www.stats.gov.cn/sj/zxfb/202602/t20260211_1962588.html",
    "https://www.stats.gov.cn/sj/zxfb/202602/t20260211_1962587.html",
)
SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")


def _months(start: str, end: str) -> list[str]:
    return expected_periods(datetime.strptime(start, "%Y-%m").date(), datetime.strptime(end, "%Y-%m").date(), "monthly")


def _next_month(period: str) -> str:
    year, month = (int(item) for item in period.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def _month_end(period: str) -> str:
    year, month = (int(item) for item in period.split("-"))
    return f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"


def _period_in(period: str, start: str, end: str) -> bool:
    return start <= period <= end


def _year_windows(start: str, end: str) -> list[tuple[str, str]]:
    return [(f"{year:04d}-01", f"{year:04d}-12") for year in range(int(start[:4]), int(end[:4]) + 1)]


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", html.unescape(str(value)))


def _field_label(value: object) -> str:
    return re.sub(r"^[一二三四五六七八九十]+、", "", _compact(value))


def _visible(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="strict")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _number(value: object) -> float:
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "—", "–", "nan", "None"}:
        raise ValueError(f"official table value is not numeric: {value!r}")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        raise ValueError(f"official table value is not numeric: {value!r}")
    return float(match.group(0))


def _meta(payload: bytes, name: str) -> str | None:
    text = payload.decode("utf-8", errors="strict")
    pattern = re.compile(
        rf"<meta[^>]+name=[\"']{re.escape(name)}[\"'][^>]+content=[\"'](.*?)[\"']",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    return html.unescape(match.group(1)).strip() if match is not None else None


def page_title(payload: bytes) -> str:
    article = _meta(payload, "ArticleTitle")
    if article:
        return article
    match = re.search(r"<title[^>]*>(.*?)</title>", payload.decode("utf-8", errors="strict"), re.I | re.S)
    return html.unescape(match.group(1)).strip() if match is not None else ""


def _publication_at(payload: bytes) -> str:
    raw = _meta(payload, "PubDate")
    if raw is None:
        match = re.search(r"(\d{4})[-/]([01]?\d)[-/]([0-3]?\d)\s+(\d{1,2}:\d{2}(?::\d{2})?)", _visible(payload))
        if match is None:
            raise ValueError("official NBS page has no publication timestamp")
        raw = "-".join(match.group(i) for i in range(1, 4)) + " " + match.group(4)
    raw = raw.strip().replace("/", "-")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw.replace(" ", "T"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"unsupported NBS publication timestamp: {raw!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_ZONE)
    else:
        parsed = parsed.astimezone(SHANGHAI_ZONE)
    return parsed.isoformat()


def infer_reference_period(title: str) -> str:
    match = re.search(r"(?P<year>20\d{2})年(?P<month>1[0-2]|0?[1-9])月份?", title)
    if match is None:
        raise ValueError(f"NBS title has no reference period: {title!r}")
    return f"{int(match.group('year')):04d}-{int(match.group('month')):02d}"


def _tables(payload: bytes) -> list[pd.DataFrame]:
    return pd.read_html(StringIO(payload.decode("utf-8", errors="strict")))


def _cpi_values(payload: bytes) -> tuple[dict[str, float], str]:
    for table in _tables(payload):
        if isinstance(table.columns, pd.MultiIndex):
            columns = list(table.columns)
            labels = [str(item) for item in columns[0]]
            yoy_index = next((i for i, item in enumerate(columns) if "同比涨跌幅" in _compact(item[0])), None)
            if yoy_index is not None:
                yoy = [str(item) for item in columns[yoy_index]]
                total_index = next((i for i, label in enumerate(labels) if _compact(label) == "居民消费价格"), None)
                core_index = next((i for i, label in enumerate(labels) if "不包括食品和能源" in _compact(label) or _compact(label) == "核心CPI"), None)
                if total_index is not None and core_index is not None:
                    return {
                        "CN.CPI.ALL.YOY": _number(yoy[total_index]),
                        "CN.CPI.CORE.YOY": _number(yoy[core_index]),
                    }, "cpi_horizontal_named_columns"
        frame = table.astype(str)
        yoy_index = next((i for i, cell in enumerate(frame.columns) if "同比涨跌幅" in _compact(cell)), None)
        if yoy_index is None:
            yoy_index = next((i for row in frame.head(min(5, len(frame))).itertuples(index=False) for i, cell in enumerate(row) if "同比涨跌幅" in _compact(cell)), None)
        if yoy_index is None:
            continue
        found: dict[str, float] = {}
        for row in frame.itertuples(index=False):
            label = _field_label(row[0]) if row else ""
            if label == "居民消费价格":
                found["CN.CPI.ALL.YOY"] = _number(row[yoy_index])
            if "不包括食品和能源" in label or label == "核心CPI":
                found["CN.CPI.CORE.YOY"] = _number(row[yoy_index])
        if set(found) == {"CN.CPI.ALL.YOY", "CN.CPI.CORE.YOY"}:
            return found, "cpi_row_named_fields"
    raise ValueError("CPI release has no named total/core同比 table fields")


def _ppi_values(payload: bytes) -> tuple[dict[str, float], str]:
    for table in _tables(payload):
        frame = table.astype(str)
        headers: dict[str, int] = {}
        for i, cell in enumerate(frame.columns):
            if "同比涨跌幅" in _compact(cell):
                headers.setdefault("yoy", i)
            if "环比涨跌幅" in _compact(cell):
                headers.setdefault("mom", i)
        for row in frame.head(min(5, len(frame))).itertuples(index=False):
            for i, cell in enumerate(row):
                if "同比涨跌幅" in _compact(cell):
                    headers.setdefault("yoy", i)
                if "环比涨跌幅" in _compact(cell):
                    headers.setdefault("mom", i)
        if set(headers) != {"yoy", "mom"}:
            continue
        found: dict[str, float] = {}
        for row in frame.itertuples(index=False):
            label = _field_label(row[0]) if row else ""
            if label == "工业生产者出厂价格":
                found["CN.PPI.ALL.YOY"] = _number(row[headers["yoy"]])
                found["CN.PPI.ALL.MOM"] = _number(row[headers["mom"]])
            if label == "工业生产者购进价格":
                found["CN.PPIRM.ALL.YOY"] = _number(row[headers["yoy"]])
        if set(found) == {"CN.PPI.ALL.YOY", "CN.PPI.ALL.MOM", "CN.PPIRM.ALL.YOY"}:
            return found, "ppi_row_named_fields"
    raise ValueError("PPI release has no named output/input price table fields")


def _regime_evidence(text: str) -> tuple[str | None, str | None, str | None]:
    compact = _compact(text)
    for base_year, regime, start in (
        ("2025", "2025_base_effective_2026-01", "2026-01"),
        ("2020", "2020_base_effective_2021-01", "2021-01"),
    ):
        if f"以{base_year}年为基期" in compact or f"{base_year}年为基期" in compact:
            return regime, base_year, start
    return None, None, None


def parse_cpi_release(payload: bytes, reference_period: str) -> dict[str, Any]:
    title = page_title(payload)
    actual_period = infer_reference_period(title)
    if actual_period != reference_period or "居民消费价格" not in _compact(title):
        raise ValueError("CPI title does not match requested reference period/type")
    values, layout = _cpi_values(payload)
    return {"values": values, "layout": layout, "title": title, "publication_at": _publication_at(payload), "reference_period": actual_period}


def parse_ppi_release(payload: bytes, reference_period: str) -> dict[str, Any]:
    title = page_title(payload)
    actual_period = infer_reference_period(title)
    if actual_period != reference_period or "工业生产者出厂价格" not in _compact(title):
        raise ValueError("PPI title does not match requested reference period/type")
    values, layout = _ppi_values(payload)
    return {"values": values, "layout": layout, "title": title, "publication_at": _publication_at(payload), "reference_period": actual_period}


def parse_interpretation(payload: bytes, reference_period: str) -> dict[str, Any]:
    title = page_title(payload)
    actual_period = infer_reference_period(title)
    compact = _compact(title) + _compact(_visible(payload))
    if actual_period != reference_period or "CPI" not in compact or "PPI" not in compact:
        raise ValueError("interpretation page does not match CPI/PPI reference period")
    regime, base_year, effective_start = _regime_evidence(compact)
    return {"title": title, "reference_period": actual_period, "publication_at": _publication_at(payload), "regime": regime, "base_year": base_year, "effective_period_start": effective_start}


def _native_path(path: Path) -> str:
    value = os.path.abspath(os.fspath(path))
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _read_bytes(path: Path) -> bytes:
    with open(_native_path(path), "rb") as handle:
        return handle.read()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    os.makedirs(_native_path(path.parent), exist_ok=True)
    if os.path.exists(_native_path(path)):
        if _read_bytes(path) != payload:
            raise RuntimeError(f"immutable file conflict: {path}")
        return
    fd, name = tempfile.mkstemp(prefix=".a", suffix=".tmp", dir=_native_path(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(name, _native_path(path))
        except FileExistsError:
            if _read_bytes(path) != payload:
                raise RuntimeError(f"immutable file conflict: {path}")
        except OSError:
            if os.path.exists(_native_path(path)):
                if _read_bytes(path) != payload:
                    raise RuntimeError(f"immutable file conflict: {path}")
            else:
                os.replace(name, _native_path(path))
        else:
            os.unlink(name)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _capture(
    output_root: Path,
    *,
    source_id: str,
    source_type: str,
    reference_period: str | None,
    request_method: str,
    request_url: str,
    parameters: dict[str, str] | None,
    status: int,
    headers: dict[str, str],
    payload: bytes,
    error: str | None,
) -> dict[str, Any]:
    retrieved = datetime.now(timezone.utc)
    digest = hashlib.sha256(payload).hexdigest()
    raw_dir = output_root / "raw" / source_id / retrieved.strftime("%Y/%m/%d")
    raw_path = raw_dir / f"{digest[:16]}.html"
    url_fingerprint = hashlib.sha256(request_url.encode("utf-8")).hexdigest()[:8]
    capture_id = retrieved.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = raw_dir / f"m-{capture_id}.json"
    sequence = 1
    while os.path.exists(_native_path(manifest_path)):
        manifest_path = raw_dir / f"m-{capture_id}-{sequence}.json"
        sequence += 1
    _atomic_bytes(raw_path, payload)
    manifest = {
        "schema_version": 1,
        "source_id": source_id,
        "source_type": source_type,
        "reference_period": reference_period,
        "retrieved_at": retrieved.isoformat(),
        "sha256": digest,
        "bytes": len(payload),
        "raw_path": raw_path.name,
        "capture_fingerprint": f"{digest}:{url_fingerprint}",
        "request": {"method": request_method.upper(), "url": request_url, "parameters": parameters or {}},
        "response": {
            "status": status,
            "headers": {str(k).lower(): str(v) for k, v in headers.items() if str(k).lower() in {"content-type", "date", "etag", "last-modified"}},
            "error": error,
        },
    }
    _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {**manifest, "manifest_path": str(manifest_path.resolve())}


def _request(method: str, url: str, *, data: bytes | None = None, accept: str = "text/html") -> tuple[int, dict[str, str], bytes, str | None]:
    request = Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urlopen(request, timeout=30) as response:
            return int(response.status), dict(response.headers.items()), response.read(), None
    except HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read(), f"HTTP_{exc.code}"
    except URLError as exc:
        return 0, {}, str(exc).encode("utf-8"), f"URL_ERROR:{exc.reason}"


def _existing_success(output_root: Path, source_id: str, method: str, url: str, parameters: dict[str, str] | None) -> dict[str, Any] | None:
    root = output_root / "raw" / source_id
    if not root.exists():
        return None
    for manifest_path in sorted(root.rglob("*.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            request = manifest.get("request", {})
            if manifest.get("response", {}).get("status") == 200 and request.get("method") == method.upper() and request.get("url") == url and request.get("parameters", {}) == (parameters or {}):
                raw_path = _manifest_raw_path(manifest_path, manifest)
                if os.path.exists(_native_path(raw_path)) and hashlib.sha256(_read_bytes(raw_path)).hexdigest() == manifest.get("sha256"):
                    return {**manifest, "manifest_path": str(manifest_path.resolve()), "raw_path": str(raw_path.resolve())}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _manifest_raw_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = Path(str(manifest["raw_path"]))
    return raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path


def _fetch_capture(
    output_root: Path,
    *,
    source_id: str,
    source_type: str,
    reference_period: str | None,
    method: str,
    url: str,
    parameters: dict[str, str] | None = None,
    data: bytes | None = None,
    accept: str = "text/html",
    retries: int = 3,
    reuse_success: bool = True,
) -> tuple[dict[str, Any], bytes]:
    if reuse_success:
        existing = _existing_success(output_root, source_id, method, url, parameters)
        if existing is not None:
            return existing, Path(str(existing["raw_path"])).read_bytes()
    last: dict[str, Any] | None = None
    last_payload = b""
    for _ in range(retries):
        status, headers, payload, error = _request(method, url, data=data, accept=accept)
        last = _capture(output_root, source_id=source_id, source_type=source_type, reference_period=reference_period, request_method=method, request_url=url, parameters=parameters, status=status, headers=headers, payload=payload, error=error)
        last_payload = payload
        if status == 200:
            return last, payload
    assert last is not None
    return last, last_payload


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._parts).strip()))
            self._href = None
            self._parts = []


def _search_query(output_root: Path, term: str, start: str, end: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query_end = _next_month(end)
    base = {
        "qt": term,
        "siteCode": SITE_CODE,
        "sort": "dateDesc",
        "keyPlace": "1",
        "timeOption": "2",
        "startDateStr": f"{start}-01",
        "endDateStr": _month_end(query_end),
    }
    result: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    page_count = 0
    total = 0
    for page in range(1, 1000):
        params = {**base, "page": str(page), "pageSize": "20"}
        manifest, payload = _fetch_capture(output_root, source_id=SEARCH_SOURCE_ID, source_type="official_search_page", reference_period=None, method="POST", url=SEARCH_URL, parameters=params, data=urlencode(params).encode("utf-8"), accept="application/json")
        pages.append(manifest)
        try:
            decoded = json.loads(payload.decode("utf-8"))
            if page == 1:
                total = int(decoded.get("totalHits", 0))
                page_count = max(1, (total + 19) // 20)
            result.extend(item.get("data", {}) for item in decoded.get("resultDocs", []))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            return result, {"term": term, "total_hits": total, "pages": pages, "page_count": page_count, "parse_failure": f"SEARCH_PAGE_{page}_NOT_JSON"}
        if page >= page_count:
            break
    return result, {"term": term, "total_hits": total, "pages": pages, "page_count": page_count, "parse_failure": None}


def _candidate_kind(title: str, url: str) -> str | None:
    compact = _compact(title)
    if not url.startswith("https://www.stats.gov.cn/") or not url.lower().endswith((".html", ".htm")):
        return None
    if re.match(r"20\d{2}年(?:1[0-2]|0?[1-9])月份?居民消费价格", compact):
        return "cpi"
    if re.match(r"20\d{2}年(?:1[0-2]|0?[1-9])月份?工业生产者出厂价格", compact):
        return "ppi"
    if "CPI" in compact and "PPI" in compact and "解读" in compact:
        return "interpretation"
    return None


def _discover(output_root: Path, start: str, end: str, *, full: bool) -> dict[str, Any]:
    listing: dict[str, Any] = {"urls": [], "periods": [], "failures": []}
    for url in LISTING_URLS:
        manifest, payload = _fetch_capture(output_root, source_id=LISTING_SOURCE_ID, source_type="official_listing_page", reference_period=None, method="GET", url=url)
        listing["urls"].append({"url": url, "status": manifest["response"]["status"], "sha256": manifest["sha256"], "manifest_path": manifest["manifest_path"]})
        if manifest["response"]["status"] != 200:
            listing["failures"].append({"url": url, "reason": "LISTING_FETCH_FAILURE"})
            continue
        parser = _LinkParser()
        try:
            parser.feed(payload.decode("utf-8"))
        except UnicodeDecodeError:
            listing["failures"].append({"url": url, "reason": "LISTING_NOT_UTF8"})
            continue
        for href, title in parser.links:
            candidate_url = urljoin(url, href)
            kind = _candidate_kind(title, candidate_url)
            if kind is not None:
                try:
                    period = infer_reference_period(title)
                except ValueError:
                    continue
                if _period_in(period, start, end):
                    listing["periods"].append(period)
    listing["periods"] = sorted(set(listing["periods"]))
    query_start = start
    all_candidates: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in ("cpi", "ppi", "interpretation")}
    search_reports: list[dict[str, Any]] = []
    for kind in ("cpi", "ppi", "interpretation"):
        report = {"term": QUERY_TERMS[kind], "total_hits": 0, "pages": [], "page_count": 0, "parse_failure": None, "official_document_count": 0, "candidate_count": 0, "candidate_periods": [], "fallback_queries": []}
        for window_start, window_end in (_year_windows(query_start, end) if full else [(query_start, end)]):
            window_start = max(window_start, query_start)
            window_end = min(window_end, end)
            if window_start > window_end:
                continue
            docs, window_report = _search_query(output_root, QUERY_TERMS[kind], window_start, window_end)
            report["total_hits"] += window_report["total_hits"]
            report["pages"].extend(window_report["pages"])
            report["page_count"] += window_report["page_count"]
            if window_report["parse_failure"] is not None:
                report["parse_failure"] = window_report["parse_failure"]
            for doc in docs:
                url = str(doc.get("url", ""))
                title = str(doc.get("titleO", ""))
                candidate = _candidate_kind(title, url)
                if candidate != kind:
                    continue
                try:
                    period = infer_reference_period(title)
                except ValueError:
                    continue
                if not _period_in(period, query_start, end):
                    continue
                report["official_document_count"] += 1
                all_candidates[kind].setdefault(period, {"url": url, "title": title, "document_date": str(doc.get("docDate", ""))})
        missing_periods = [period for period in _months(start, end) if period not in all_candidates[kind]]
        for period in missing_periods:
            month = int(period[5:])
            fallback_term = f"{period[:4]}年{month}月份" + ("居民消费价格" if kind == "cpi" else "工业生产者出厂价格" if kind == "ppi" else "CPI PPI")
            docs, fallback_report = _search_query(output_root, fallback_term, period, _next_month(period))
            report["fallback_queries"].append({"term": fallback_term, "total_hits": fallback_report["total_hits"], "pages": len(fallback_report["pages"]), "parse_failure": fallback_report["parse_failure"]})
            for doc in docs:
                url = str(doc.get("url", ""))
                title = str(doc.get("titleO", ""))
                if _candidate_kind(title, url) != kind:
                    continue
                try:
                    discovered_period = infer_reference_period(title)
                except ValueError:
                    continue
                if discovered_period == period:
                    all_candidates[kind].setdefault(period, {"url": url, "title": title, "document_date": str(doc.get("docDate", ""))})
        report["candidate_count"] = len(all_candidates[kind])
        report["candidate_periods"] = sorted(all_candidates[kind])
        search_reports.append(report)
    return {"listing": listing, "search": search_reports, "candidates": all_candidates, "query_start": query_start}


def _methodology(output_root: Path, end: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del end
    evidence: list[dict[str, Any]] = []
    for url in METHODOLOGY_SEED_URLS:
        manifest, payload = _fetch_capture(output_root, source_id=METHODOLOGY_SOURCE_ID, source_type="official_methodology_page", reference_period=None, method="GET", url=url)
        if manifest["response"]["status"] != 200:
            continue
        regime, base_year, effective_start = _regime_evidence(_visible(payload))
        if regime is not None:
            evidence.append({"url": url, "title": page_title(payload), "regime": regime, "base_year": base_year, "effective_period_start": effective_start, "sha256": manifest["sha256"], "manifest_path": manifest["manifest_path"]})
    unique = {(item["regime"], item["base_year"]): item for item in evidence}
    return list(unique.values()), [{"seed_urls": list(METHODOLOGY_SEED_URLS), "official_methodology_evidence": len(unique), "pages": len(METHODOLOGY_SEED_URLS), "parse_failure": None}]


def _raw_hash_audit(output_root: Path) -> dict[str, Any]:
    checked = 0
    failures: list[str] = []
    source_roots = [output_root / "raw" / source_id for source_id in (SOURCE_ID, SEARCH_SOURCE_ID, LISTING_SOURCE_ID, METHODOLOGY_SOURCE_ID)]
    for source_root in source_roots:
        if not source_root.exists():
            continue
        for manifest_path in source_root.rglob("*.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                raw = _manifest_raw_path(manifest_path, manifest)
                checked += 1
                if not os.path.exists(_native_path(raw)) or hashlib.sha256(_read_bytes(raw)).hexdigest() != manifest.get("sha256"):
                    failures.append(str(manifest_path))
            except (OSError, ValueError, KeyError, TypeError):
                failures.append(str(manifest_path))
    return {"checked": checked, "failures": failures, "valid": not failures}


def _row(series_id: str, period: str, value: float, *, url: str, manifest: dict[str, Any], publication_at: str, layout: str, regime: str) -> dict[str, Any]:
    raw_sha = str(manifest["sha256"])
    source_record_id = f"{SOURCE_ID}:{hashlib.sha256(url.encode()).hexdigest()[:16]}:{series_id}"
    return {
        "series_id": series_id,
        "reference_period": period,
        "value": value,
        "unit": "percent_mom" if series_id == "CN.PPI.ALL.MOM" else "percent_yoy",
        "seasonal_adjustment": "not_applicable",
        "source_id": SOURCE_ID,
        "source_record_id": source_record_id,
        "release_at": publication_at,
        "available_at": publication_at,
        "tradable_at": publication_at,
        "availability_evidence": f"official NBS {layout} release page; methodology regime {regime}",
        "retrieved_at": str(manifest["retrieved_at"]),
        "vintage_id": f"nbs_prices_release:{period}:{raw_sha[:16]}",
        "raw_sha256": raw_sha,
        "parser_version": PARSER_VERSION,
        "schema_version": 2,
        "reference_period_start": period,
        "reference_period_end": period,
        "period_span": period,
        "measure_basis": "period_observation",
        "methodology_version": METHODOLOGY_VERSION,
        "regime_id": regime,
        "pit_grade": "A",
        "license_scope": "internal_research",
    }


def run_history_shadow(output_root: Path, start: str, end: str, *, full: bool = False) -> dict[str, Any]:
    discovery = _discover(output_root, start, end, full=full)
    methodology, methodology_search = _methodology(output_root, end)
    available_regimes = {str(item["regime"]) for item in methodology}
    parse_failures: list[dict[str, Any]] = []
    fetch_failures: list[dict[str, Any]] = []
    page_missing: list[dict[str, Any]] = []
    method_blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    period_audit: dict[str, Any] = {}
    expected = _months(start, end)

    for period in expected:
        period_audit[period] = {"cpi": None, "ppi": None, "interpretation": None, "missing_series": []}
        regime = "2025_base_effective_2026-01" if period >= "2026-01" else "2020_base_effective_2021-01"
        if regime not in available_regimes:
            method_blockers.append({"code": "METHODOLOGY_EVIDENCE_MISSING", "reference_period": period, "expected_regime": regime})
        for kind, source_type in (
            ("cpi", "official_cpi_release"),
            ("ppi", "official_ppi_release"),
            ("interpretation", "official_interpretation"),
        ):
            candidate = discovery["candidates"][kind].get(period)
            if candidate is None:
                page_missing.append({"reference_period": period, "source_type": source_type, "reason": "OFFICIAL_PAGE_NOT_DISCOVERED"})
                continue
            manifest, payload = _fetch_capture(
                output_root,
                source_id=SOURCE_ID,
                source_type=source_type,
                reference_period=period,
                method="GET",
                url=str(candidate["url"]),
            )
            if manifest["response"]["status"] != 200:
                fetch_failures.append({"reference_period": period, "source_type": source_type, "status": manifest["response"]["status"], "url": candidate["url"]})
                continue
            try:
                if kind == "cpi":
                    parsed = parse_cpi_release(payload, period)
                elif kind == "ppi":
                    parsed = parse_ppi_release(payload, period)
                else:
                    parsed = parse_interpretation(payload, period)
                period_audit[period][kind] = {
                    "url": candidate["url"],
                    "sha256": manifest["sha256"],
                    "manifest_path": manifest["manifest_path"],
                    "layout": parsed.get("layout"),
                    "regime": parsed.get("regime"),
                }
                if kind in {"cpi", "ppi"}:
                    for series_id, value in parsed["values"].items():
                        rows.append(_row(series_id, period, value, url=str(candidate["url"]), manifest=manifest, publication_at=str(parsed["publication_at"]), layout=str(parsed["layout"]), regime=regime))
                elif parsed.get("regime") is not None and parsed["regime"] != regime:
                    method_blockers.append({"code": "METHODOLOGY_REGIME_MISMATCH", "reference_period": period, "page_regime": parsed["regime"], "expected_regime": regime})
            except (ValueError, KeyError, IndexError) as exc:
                parse_failures.append({"reference_period": period, "source_type": source_type, "url": candidate["url"], "error": str(exc)})
        for series_id in SERIES:
            if not any(row["series_id"] == series_id and row["reference_period"] == period for row in rows):
                period_audit[period]["missing_series"].append(series_id)

    frame = pd.DataFrame(rows, columns=CANONICAL_V2_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["reference_period", "series_id", "vintage_id"], kind="mergesort").reset_index(drop=True)
    duplicate_keys = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not frame.empty else 0
    domain_failures = int((~frame["value"].between(-100.0, 100.0)).sum()) if not frame.empty else 0
    observed = sorted(period for period in expected if not period_audit[period]["missing_series"])
    missing_cells = [
        f"{period}|{series_id}"
        for period in expected
        for series_id in SERIES
        if not any(row["series_id"] == series_id and row["reference_period"] == period for row in rows)
    ]
    known_failure_periods = {str(item["reference_period"]) for item in page_missing + fetch_failures + parse_failures}
    unexplained = [cell for cell in missing_cells if cell.split("|", 1)[0] not in known_failure_periods]

    blockers: list[dict[str, Any]] = []
    if discovery["listing"]["failures"]:
        blockers.append({"code": "LISTING_QUARANTINED", "detail": discovery["listing"]["failures"]})
    if any(item.get("parse_failure") for item in discovery["search"]):
        blockers.append({"code": "SEARCH_PARSE_FAILURE", "detail": discovery["search"]})
    if page_missing or fetch_failures or parse_failures or unexplained:
        blockers.append({"code": "OFFICIAL_COVERAGE_INCOMPLETE", "detail": {"page_missing": page_missing, "fetch_failures": fetch_failures, "parse_failures": parse_failures, "unexplained": unexplained}})
    blockers.extend(method_blockers)
    hash_audit = _raw_hash_audit(output_root)
    if not hash_audit["valid"]:
        blockers.append({"code": "RAW_HASH_INVALID", "detail": hash_audit["failures"]})
    canonical = validate_canonical_v2(frame) if not frame.empty else {"passed": False, "failures": ["empty_frame"], "rows": 0}
    if not canonical["passed"]:
        blockers.append({"code": "CANONICAL_V2_INVALID", "detail": canonical["failures"]})

    source = {
        "source_id": SOURCE_ID,
        "history_scope": {
            "long_history_target": "NBS CPI/PPI history beyond the PIT-A window; not claimed in this candidate",
            "pit_a_window": {"start": "2021-01", "end": "2026-07", "status": "release_window"},
            "pre_2021_status": "deferred_pit_c_exploratory_not_acquired",
            "requested_window": {"start": start, "end": end},
        },
        "official_listing": {"urls": LISTING_URLS, "periods": discovery["listing"]["periods"], "coverage_count": len(discovery["listing"]["periods"])},
        "official_search_replay": discovery["search"],
        "methodology_evidence": methodology,
        "methodology_search": methodology_search,
        "actual_download": {
            "period_count": len({p for p, item in period_audit.items() if item["cpi"] and item["ppi"]}),
            "cpi_pages": sum(bool(v["cpi"]) for v in period_audit.values()),
            "ppi_pages": sum(bool(v["ppi"]) for v in period_audit.values()),
            "interpretation_pages": sum(bool(v["interpretation"]) for v in period_audit.values()),
        },
        "successful_parse": {
            "period_count": len(observed),
            "periods": observed,
            "rows": len(rows),
            "layouts": {
                "cpi": sorted({str(v["cpi"].get("layout")) for v in period_audit.values() if v["cpi"]}),
                "ppi": sorted({str(v["ppi"].get("layout")) for v in period_audit.values() if v["ppi"]}),
            },
        },
        "expected_period_coverage": {"expected_periods": expected, "observed_periods": observed, "missing_cells": missing_cells, "period_audit": period_audit},
        "raw_hash": hash_audit,
        "parse_failures": parse_failures,
        "fetch_failures": fetch_failures,
        "official_page_missing": page_missing,
        "methodology_blockers": method_blockers,
        "duplicate_primary_keys": duplicate_keys,
        "value_domain_failures": domain_failures,
        "canonical_v2": canonical,
        "pit_grade": "A",
        "license_scope": "internal_research",
        "projection_mismatches": [],
    }
    audit = build_audit(
        package_id="prices",
        run_mode="full" if full else "shadow",
        start=start,
        end=end,
        expected=expected,
        observed=observed,
        sources=[source],
        blockers=blockers,
        unexplained_missing=unexplained,
        structural_omissions=page_missing,
        raw_hashes_valid=hash_audit["valid"],
        duplicate_primary_keys=duplicate_keys,
        value_domain_failures=domain_failures,
    )
    validation = validate_audit(audit)
    return {"audit": audit, "validation": validation, "research_ready": False, "_frame": frame, "source": source, "candidate_rows": len(rows)}


def run_full_candidate(output_root: Path, start: str = "2021-01", end: str = "2026-07") -> dict[str, Any]:
    return run_history_shadow(output_root, start, end, full=True)
