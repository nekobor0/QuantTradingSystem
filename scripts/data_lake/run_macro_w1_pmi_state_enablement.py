"""Official NBS PMI state discovery and bounded shadow enablement.

This entry point deliberately stops at the bounded shadow window.  It is not a
full-history backfill runner and never changes the package full-history gate.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urljoin

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import (  # noqa: E402
    CANONICAL_COLUMNS,
    RawSnapshot,
    capture_raw_snapshot,
    validate_canonical_v2,
    write_canonical_v2_snapshot,
)
from quant_trading_system.research.macro_data.adapters import _TableParser  # noqa: E402
from quant_trading_system.research.macro_data.w1_execution import (  # noqa: E402
    build_audit,
    expected_periods,
    validate_audit,
)


SOURCE_ID = "nbs_pmi_state_release"
LISTING_URL = "https://www.stats.gov.cn/sj/zxfb/"
PARSER_VERSION = "r011.w1.pmi_state.enablement.v1"
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
    SERIES[0]: "2009-05",
    SERIES[1]: "2009-05",
    SERIES[2]: "2014-11",
    SERIES[3]: "2014-11",
    SERIES[4]: "2018-01",
    SERIES[5]: "2018-01",
    SERIES[6]: "2018-01",
    SERIES[7]: "2018-01",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", " ", text)))


def _period(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{4})\D{1,8}(\d{1,2})(?!\d)", text)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


def _number(value: Any) -> float:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
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
    for rows in parser.tables:
        for index, row in enumerate(rows):
            if not row or str(row[0]).strip().upper() != "PMI" or index == 0:
                continue
            header = rows[index - 1]
            periods = [_period(str(item)) for item in header[1:]]
            if not any(periods):
                raw_periods = [_period(match.group(0)) for match in re.finditer(r"\d{4}[年/-]\d{1,2}[月]?", payload.decode("utf-8", errors="strict"))]
                if len(raw_periods) == 1:
                    periods = raw_periods
            if reference_period not in periods:
                continue
            column = periods.index(reference_period) + 1
            series_rows = rows[index:index + 6]
            if len(series_rows) < 3:
                continue
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
    if not match:
        visible = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
        match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)", visible)
    if not match:
        raise ValueError("official PMI page has no publication timestamp")
    year, month, day, clock = match.groups()
    if clock.count(":") == 1:
        clock += ":00"
    return f"{year}-{int(month):02d}-{int(day):02d}T{clock}+08:00"


def parse_pmi_state_release(payload: bytes, reference_period: str) -> PmiParseResult:
    """Parse only fields explicitly present for one official release period."""
    tables = pd.read_html(BytesIO(payload))
    if not tables:
        raise ValueError("official PMI release has no HTML tables")
    publication_at = _publication_at(payload)
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
    for series_id in SERIES[2:4]:
        if series_id not in values:
            omissions.append({"series_id": series_id, "reference_period": reference_period, "reason": "SERIES_NOT_PUBLISHED_IN_LAYOUT"})
    if len(tables) >= 3:
        nonmfg = _target_row(tables[2], reference_period)
        if nonmfg is not None and len(nonmfg) >= 4:
            values["CN.PMI.NONMFG.ACTIVITY"] = _number(nonmfg[1])
            values["CN.PMI.NONMFG.NEW_ORDERS"] = _number(nonmfg[2])
            values["CN.PMI.NONMFG.INPUT_PRICE"] = _number(nonmfg[3])
    for series_id in SERIES[4:7]:
        if series_id not in values:
            omissions.append({"series_id": series_id, "reference_period": reference_period, "reason": "SERIES_NOT_PUBLISHED_IN_LAYOUT"})
    match = re.search(r"综合PMI产出指数(?:为|是)([-+]?\d+(?:\.\d+)?)%", _compact(payload.decode("utf-8", errors="strict")))
    if match:
        values["CN.PMI.COMPOSITE.OUTPUT"] = float(match.group(1))
    else:
        omissions.append({"series_id": SERIES[7], "reference_period": reference_period, "reason": "SERIES_NOT_PUBLISHED_IN_LAYOUT"})
    rows = tuple({"series_id": series_id, "reference_period": reference_period, "value": values[series_id]} for series_id in SERIES if series_id in values)
    return PmiParseResult(rows, tuple(omissions), publication_at, layout)


class _ReleaseLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._title: str = ""
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        data = dict(attrs)
        self._href = data.get("href")
        self._title = data.get("title") or ""
    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._title += data
    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._title.split())))
            self._href, self._title = None, ""


def _fetch(url: str) -> tuple[int, dict[str, str], bytes, str | None]:
    request = Request(url, headers={"User-Agent": "QuantTradingSystem-W1-research/1.0", "Accept": "text/html"})
    try:
        with urlopen(request, timeout=8) as response:
            return int(response.status), dict(response.headers.items()), response.read(), None
    except HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read(), f"HTTP_{exc.code}"
    except URLError as exc:
        return 0, {}, b"", f"NETWORK_{exc.reason}"
    except TimeoutError:
        return 0, {}, b"", "NETWORK_TIMEOUT"


def _pseudo(status: int, headers: dict[str, str], payload: bytes) -> bool:
    content_type = headers.get("Content-Type", headers.get("content-type", "")).lower()
    sample = payload[:4096].decode("utf-8", errors="ignore").lower()
    return status != 200 or "html" not in content_type or any(token in sample for token in ("验证码", "captcha", "access denied"))


def _page_url(index: int) -> str:
    return LISTING_URL if index == 0 else f"{LISTING_URL}index_{index}.html"


def _release_url(href: str) -> str:
    return urljoin(LISTING_URL, href)


def discover_release_pages(output_root: Path, quarantine: list[dict[str, Any]]) -> list[dict[str, str]]:
    first_status, first_headers, first_payload, error = _fetch(LISTING_URL)
    first_snapshot = capture_raw_snapshot(
        output_root=output_root, source_id=f"{SOURCE_ID}_index", payload=first_payload,
        retrieved_at=datetime.now(timezone.utc), request_method="GET", request_url=LISTING_URL,
        response_status=first_status, response_headers=first_headers, extension="html",
    )
    if error or _pseudo(first_status, first_headers, first_payload):
        quarantine.append({"url": LISTING_URL, "status": first_status, "reason": error or "PSEUDO_RESPONSE", "raw_sha256": first_snapshot.sha256})
        return []
    count_match = re.search(r"createPageHTML\((\d+),\s*0", first_payload.decode("utf-8", errors="ignore"))
    page_count = int(count_match.group(1)) if count_match else 1
    payloads = [(0, first_payload, first_snapshot)]
    for index in range(1, page_count):
        url = _page_url(index)
        status, headers, payload, fetch_error = _fetch(url)
        snapshot = capture_raw_snapshot(
            output_root=output_root, source_id=f"{SOURCE_ID}_index", payload=payload,
            retrieved_at=datetime.now(timezone.utc), request_method="GET", request_url=url,
            response_status=status, response_headers=headers, extension="html",
        )
        if fetch_error or _pseudo(status, headers, payload):
            quarantine.append({"url": url, "status": status, "reason": fetch_error or "PSEUDO_RESPONSE", "raw_sha256": snapshot.sha256})
            continue
        payloads.append((index, payload, snapshot))
    releases: dict[str, dict[str, str]] = {}
    for index, payload, snapshot in payloads:
        parser = _ReleaseLinks()
        parser.feed(payload.decode("utf-8", errors="strict"))
        for href, title in parser.links:
            if "采购经理指数" not in title or "解读" in title or "答记者问" in title:
                continue
            period = _period(title) or _period(href)
            if not period or not href.lower().endswith((".html", ".htm")):
                continue
            url = _release_url(href)
            if "www.stats.gov.cn" not in url:
                continue
            releases.setdefault(period, {"reference_period": period, "url": url, "discovery_index": str(index), "index_raw_sha256": snapshot.sha256})
    return [releases[key] for key in sorted(releases)]


def load_existing_release_archive(output_root: Path, periods: list[str]) -> list[dict[str, str]]:
    """Load previously captured official pages without treating them as new discovery."""
    catalog_path = output_root / "catalogs" / "pmi_release_pages.json"
    archive_root = output_root / "raw" / "nbs_pmi_release_archive"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest_by_url: dict[str, dict[str, Any]] = {}
    for manifest_path in archive_root.rglob("*.manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["_manifest_path"] = str(manifest_path)
        request = manifest.get("request", {})
        if manifest.get("response", {}).get("status") == 200 and request.get("url"):
            manifest_by_url[str(request["url"])] = manifest
    result: list[dict[str, str]] = []
    for item in catalog.get("pages", []):
        period = str(item.get("reference_period") or "")
        url = str(item.get("url") or "")
        if period not in periods or url not in manifest_by_url:
            continue
        manifest = manifest_by_url[url]
        raw_path = str(manifest["raw_path"])
        if Path(raw_path).exists():
            result.append({
                "reference_period": period, "url": url, "raw_path": raw_path,
                "manifest_path": str(manifest["_manifest_path"]),
                "archive_manifest_source_id": str(manifest.get("source_id", "")),
                "archive_sha256": str(manifest["sha256"]),
            })
    return result


def _record(row: dict[str, Any], snapshot: RawSnapshot, publication_at: str, layout: str) -> dict[str, Any]:
    source_record_id = f"{layout}|{row['reference_period']}|{row['series_id']}"
    return {
        "series_id": row["series_id"], "reference_period": row["reference_period"], "value": row["value"],
        "unit": "diffusion_index_percent", "seasonal_adjustment": "seasonally_adjusted",
        "source_id": SOURCE_ID, "source_record_id": source_record_id,
        "release_at": publication_at, "available_at": publication_at, "tradable_at": publication_at,
        "availability_evidence": "observed_official_nbs_release_page_timestamp",
        "retrieved_at": snapshot.retrieved_at, "vintage_id": f"{SOURCE_ID}:{snapshot.sha256[:16]}",
        "raw_sha256": snapshot.sha256, "parser_version": PARSER_VERSION,
    }


def expected_series_periods(start: str, end: str) -> dict[str, list[str]]:
    months = expected_periods(datetime.strptime(start, "%Y-%m").date(), datetime.strptime(end, "%Y-%m").date(), "monthly")
    return {series_id: [item for item in months if item >= SERIES_START[series_id]] for series_id in SERIES}


def run(output_root: Path, shadow_start: str, shadow_end: str, *, offline_existing_archive: bool = False) -> dict[str, Any]:
    quarantine: list[dict[str, Any]] = []
    periods = expected_periods(datetime.strptime(shadow_start, "%Y-%m").date(), datetime.strptime(shadow_end, "%Y-%m").date(), "monthly")
    releases = load_existing_release_archive(output_root, periods) if offline_existing_archive else discover_release_pages(output_root, quarantine)
    by_period = {item["reference_period"]: item for item in releases}
    records: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    for period in periods:
        candidate = by_period.get(period)
        if candidate is None:
            quarantine.append({"reference_period": period, "reason": "DISCOVERY_FAILED"})
            continue
        if candidate.get("raw_path"):
            payload = Path(candidate["raw_path"]).read_bytes()
            manifest = json.loads(Path(candidate["manifest_path"]).read_text(encoding="utf-8")) if candidate.get("manifest_path") else {}
            status = int(manifest.get("response", {}).get("status", 200))
            headers = {str(key): str(value) for key, value in manifest.get("response", {}).get("headers", {}).items()}
            error = None
            snapshot = RawSnapshot(
                source_id=SOURCE_ID, retrieved_at=str(manifest["retrieved_at"]), sha256=hashlib.sha256(payload).hexdigest(),
                bytes=len(payload), raw_path=str(Path(candidate["raw_path"]).resolve()), manifest_path=str(Path(candidate["manifest_path"]).resolve()),
                request_method="GET", request_url=candidate["url"], response_status=status, content_type=headers.get("content-type", "text/html"),
            )
        else:
            status, headers, payload, error = _fetch(candidate["url"])
            snapshot = capture_raw_snapshot(
                output_root=output_root, source_id=SOURCE_ID, payload=payload,
                retrieved_at=datetime.now(timezone.utc), request_method="GET", request_url=candidate["url"],
                response_status=status, response_headers=headers, extension="html",
            )
        if error or _pseudo(status, headers, payload):
            quarantine.append({"reference_period": period, "url": candidate["url"], "status": status, "reason": error or "PSEUDO_RESPONSE", "raw_sha256": snapshot.sha256})
            continue
        try:
            parsed = parse_pmi_state_release(payload, period)
        except (ValueError, ImportError) as exc:
            parse_failures.append({"reference_period": period, "url": candidate["url"], "reason": str(exc), "raw_sha256": snapshot.sha256})
            continue
        records.extend(_record(row, snapshot, parsed.publication_at, parsed.layout) for row in parsed.rows)
        omissions.extend({**item, "url": candidate["url"], "raw_sha256": snapshot.sha256} for item in parsed.structural_omissions)
    frame = pd.DataFrame(records, columns=CANONICAL_COLUMNS)
    if records:
        v2 = frame.copy()
        v2["schema_version"] = 2
        v2["reference_period_start"] = v2["reference_period"]
        v2["reference_period_end"] = v2["reference_period"]
        v2["period_span"] = v2["reference_period"]
        v2["measure_basis"] = "period_observation"
        v2["methodology_version"] = "nbs_pmi_state_frozen_field_mapping_v1"
        v2["regime_id"] = "pmi_state"
        v2["pit_grade"] = "UNASSESSED"
        v2["license_scope"] = "public_redistributable"
        v2 = v2[[*CANONICAL_COLUMNS, "schema_version", "reference_period_start", "reference_period_end", "period_span", "measure_basis", "methodology_version", "regime_id", "pit_grade", "license_scope"]]
        validation = validate_canonical_v2(v2)
        if not validation["passed"]:
            raise ValueError(f"canonical v2 validation failed: {validation['failures']}")
        write_canonical_v2_snapshot(v2, output_root / "normalized" / "pmi_state_bounded_shadow.parquet")
    expected_by_series = expected_series_periods(shadow_start, shadow_end)
    observed_by_series = {series_id: sorted({row["reference_period"] for row in records if row["series_id"] == series_id}) for series_id in SERIES}
    unexplained = [f"{series_id}|{period}" for series_id, expected in expected_by_series.items() for period in expected if period not in observed_by_series[series_id] and not any(item.get("series_id") == series_id and item.get("reference_period") == period for item in omissions)]
    blockers = []
    if quarantine or parse_failures or unexplained:
        blockers.append({"code": "PMI_SHADOW_UNEXPLAINED", "detail": "official discovery/fetch/parse gaps remain"})
    source = {
        "source_id": SOURCE_ID, "official_listing": LISTING_URL, "discovered_release_count": len(releases),
        "input_mode": "existing_official_raw_archive" if offline_existing_archive else "official_pagination_fetch",
        "shadow_periods": periods, "expected_by_series": expected_by_series, "observed_by_series": observed_by_series,
        "parse_failures": parse_failures, "quarantine": quarantine,
        "discovery_raw_hashes": sorted({item.get("index_raw_sha256", item.get("archive_sha256", "")) for item in releases}),
    }
    audit = build_audit(
        package_id="pmi_state", run_mode="shadow", start=shadow_start, end=shadow_end,
        expected=periods, observed=sorted({row["reference_period"] for row in records}), sources=[source],
        blockers=blockers, unexplained_missing=unexplained, structural_omissions=omissions,
        raw_hashes_valid=not any(item.get("raw_sha256") == "" for item in quarantine),
        duplicate_primary_keys=int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if records else 0,
        value_domain_failures=int((~frame["value"].between(0, 100)).sum()) if records else 0,
    )
    validation = validate_audit(audit)
    result = {"audit": audit, "validation": validation, "research_ready": False}
    audit_path = output_root / "audits" / "w1_pmi_state_enablement.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow-start", default="2024-08")
    parser.add_argument("--shadow-end", default="2026-07")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--mode", choices=("shadow",), default="shadow")
    parser.add_argument("--offline-existing-release-archive", action="store_true")
    args = parser.parse_args()
    result = run(args.output_root, args.shadow_start, args.shadow_end, offline_existing_archive=args.offline_existing_release_archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["validation"]["passed"] and not result["audit"]["blocked"] else 1)


if __name__ == "__main__":
    main()
