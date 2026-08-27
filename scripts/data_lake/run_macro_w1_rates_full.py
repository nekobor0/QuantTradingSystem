"""Capture the official PBOC announcement history for the frozen W1 rate scope.

CFETS is deliberately evidence-only here: the public daily endpoint is not
promoted to a full-history source until an independent path and a real strategy
calendar both pass the frozen acceptance rules.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.adapters import parse_pboc_policy_release
from quant_trading_system.research.macro_data.backfill import (
    _quarantine_request,
    _request_and_snapshot,
    _write_json,
    _write_rate_shard,
)
from quant_trading_system.research.macro_data.contracts import CANONICAL_COLUMNS, RawSnapshot, snapshot_as_dict, write_normalized_snapshot


PBOC_HOSTS = {"pbc.gov.cn", "www.pbc.gov.cn"}
SEARCH_URL = "https://wzdig.pbc.gov.cn/search/pcRender"
SEARCH_PAGE_ID = "c177a85bd02b4114bebebd210809f691"
SEARCH_TOTAL_RE = re.compile(r'id="default-result-total-pages" value="(\d+)"')
OMO_TOTAL_RE = re.compile(r'totalpage="(\d+)"')
OMO_PAGE_RE = re.compile(r'tagname="([^"]+-\d+\.html)"')


def _official(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return host in PBOC_HOSTS or host.endswith(".pbc.gov.cn")


def _is_html_page(payload: bytes) -> bool:
    text = payload.decode("utf-8", errors="ignore").lower()
    return "<html" in text and "</html>" in text and "captcha" not in text and "验证码" not in text


def _links(payload: bytes, base_url: str) -> list[dict[str, str]]:
    from quant_trading_system.research.macro_data.backfill import _AnchorParser

    parser = _AnchorParser()
    parser.feed(payload.decode("utf-8", errors="strict"))
    result = []
    for item in parser.links:
        url = urljoin(base_url, html.unescape(item["href"]))
        if _official(url):
            result.append({"url": url, "text": " ".join(item["text"].split())})
    return result


def _capture_index(output_root: Path, source_id: str, url: str) -> tuple[bytes, RawSnapshot]:
    response, snapshot = _request_and_snapshot(
        output_root=output_root,
        source_id=source_id,
        url=url,
        method="GET",
        data=None,
        extension="html",
    )
    if response.status != 200:
        raise ValueError(f"non-200 index response: {response.status}")
    if not _is_html_page(response.payload):
        raise ValueError("index response is an HTML pseudo-response, CAPTCHA, or malformed page")
    return response.payload, snapshot


def _page_urls(first_payload: bytes, base_url: str) -> list[str]:
    match = OMO_TOTAL_RE.search(first_payload.decode("utf-8", errors="ignore"))
    if match is None:
        raise ValueError("PBOC OMO index has no official pagination total")
    total = int(match.group(1))
    candidates = [urljoin(base_url, item.group(1)) for item in OMO_PAGE_RE.finditer(first_payload.decode("utf-8", errors="ignore"))]
    numbered = next((item for item in candidates if re.search(r"-\d+\.html$", item)), None)
    if total > 1 and numbered is None:
        raise ValueError("PBOC OMO index has no next-page URL")
    if numbered is None:
        return [base_url]
    return [re.sub(r"-\d+\.html$", f"-{number}.html", numbered) for number in range(1, total + 1)]


def _omo_announcements(index_pages: list[bytes], index_urls: list[str]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for payload, base_url in zip(index_pages, index_urls):
        for item in _links(payload, base_url):
            if "公开市场业务交易公告" in item["text"]:
                found[item["url"]] = item
    return sorted(found.values(), key=lambda item: item["url"])


def _mlf_search_url(page_no: int) -> str:
    query = {
        "q": "中期借贷便利",
        "sr": "score desc",
        "pageId": SEARCH_PAGE_ID,
        "ext": "",
        "pNo": str(page_no),
    }
    return f"{SEARCH_URL}?{urlencode(query)}"


def _mlf_search_pages(output_root: Path, total_hint: int | None = None) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    first_payload, first_snapshot = _capture_index(output_root, "pboc_mlf_site_search", _mlf_search_url(1))
    first_text = first_payload.decode("utf-8", errors="strict")
    match = SEARCH_TOTAL_RE.search(first_text)
    if match is None:
        raise ValueError("PBOC MLF site search has no official pagination total")
    total = int(match.group(1))
    if total_hint is not None:
        total = min(total, total_hint)
    captured: list[dict[str, Any]] = [{"url": _mlf_search_url(1), "snapshot": snapshot_as_dict(first_snapshot), "status": 200}]
    pages = [first_payload]
    for page_no in range(2, total + 1):
        payload, snapshot = _capture_index(output_root, "pboc_mlf_site_search", _mlf_search_url(page_no))
        pages.append(payload)
        captured.append({"url": _mlf_search_url(page_no), "snapshot": snapshot_as_dict(snapshot), "status": 200})
    found: dict[str, dict[str, str]] = {}
    for payload in pages:
        for item in _links(payload, SEARCH_URL):
            if "中期借贷便利" in item["text"] and ("/125446/" in item["url"] or "/3750260/" in item["url"]):
                found[item["url"]] = item
    return sorted(found.values(), key=lambda item: item["url"]), captured


def _fetch_and_parse(
    output_root: Path, kind: str, item: dict[str, str]
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    source_id = "pboc_omo_release" if kind == "omo" else "pboc_mlf_release"
    try:
        response, snapshot = _request_and_snapshot(
            output_root=output_root,
            source_id=source_id,
            url=item["url"],
            method="GET",
            data=None,
            extension="html",
        )
        if response.status != 200:
            raise ValueError(f"non-200 release response: {response.status}")
        if not _is_html_page(response.payload):
            raise ValueError("release response is an HTML pseudo-response, CAPTCHA, or malformed page")
        parsed = parse_pboc_policy_release(
            response.payload,
            snapshot,
            source_file=Path(urlsplit(item["url"]).path).name,
        )
        _write_rate_shard(
            output_root,
            parsed.observations,
            snapshot,
            {
                "page_url": item["url"],
                "page_timestamp": parsed.page_timestamp.isoformat(),
                "event_kind": parsed.event_kind,
                "omissions": list(parsed.omissions),
            },
        )
        return {
            "status": "PARSED",
            "url": item["url"],
            "page_timestamp": parsed.page_timestamp.isoformat(),
            "event_kind": parsed.event_kind,
            "omissions": list(parsed.omissions),
            "snapshot": snapshot_as_dict(snapshot),
        }, parsed.observations
    except Exception as exc:
        detail = {
            "source": item["url"],
            "method": "GET",
            "error": f"{type(exc).__name__}: {exc}",
        }
        url_key = hashlib.sha256(item["url"].encode("utf-8")).hexdigest()[:16]
        qpath = _quarantine_request(output_root, f"pboc_full_{kind}_{url_key}", detail)
        return {"status": "QUARANTINED", "url": item["url"], "reason": detail["error"], "quarantine": qpath}, None


def _calendar_evidence(output_root: Path, calendar_path: Path, start: str, end: str) -> dict[str, Any]:
    result: dict[str, Any] = {"source": str(calendar_path.resolve()), "status": "BLOCKED"}
    try:
        frame = pd.read_parquet(calendar_path)
        required = {"exchange", "cal_date", "is_open"}
        if not required.issubset(frame.columns):
            raise ValueError(f"calendar missing columns: {sorted(required - set(frame.columns))}")
        sse = frame[frame["exchange"].astype(str).eq("SSE")].copy()
        dates = sse["cal_date"].astype(str).str.replace("-", "", regex=False)
        start_key, end_key = start.replace("-", ""), end.replace("-", "")
        if dates.min() > start_key or dates.max() < end_key:
            raise ValueError(f"calendar coverage is {dates.min()}..{dates.max()}, required through {end}")
        open_dates = sorted(
            f"{value[:4]}-{value[4:6]}-{value[6:]}"
            for value in dates[sse["is_open"].astype(str).eq("1")]
            if start_key <= value
        )
        later = [value for value in open_dates if value > end]
        if not later:
            raise ValueError("calendar has no open date after end date")
        path = output_root / "state" / "w1_rates_luna_full" / "strategy_trading_days.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(open_dates) + "\n", encoding="utf-8")
        result.update({"status": "OK", "path": str(path.resolve()), "dates": open_dates})
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _cfets_evidence(output_root: Path, prior_audit: Path) -> list[dict[str, Any]]:
    prior = json.loads(prior_audit.read_text(encoding="utf-8")) if prior_audit.exists() else {}
    captured = prior.get("captured", [])
    early = [item for item in captured if item.get("source_id") == "cfets_repo_daily"][:3]
    recent = [item for item in captured if item.get("source_id") == "cfets_repo_daily"][-3:]
    return [
        {
            "mechanism_id": "public_daily_post_api",
            "official_identity": "ChinaMoney/CFETS public daily repo product",
            "url": "https://www.chinamoney.com.cn/ags/ms/cm-u-dlrp/PrDlyBltn",
            "method": "POST",
            "params": {"lang": "cn", "publishedTime": "2200", "searchDate": "per-request", "indexType": "markInterBankVOList|markVOList"},
            "acceptance": "FAILED: no verified historical path; prior shadow had repeatable empty records for early dates",
            "early_recent_evidence": early + recent,
        },
        {
            "mechanism_id": "public_daily_product_page",
            "official_identity": "ChinaMoney/CFETS public daily repo product page",
            "url": "https://www.chinamoney.com.cn/chinese/mtdexdaily/?tab=2",
            "method": "GET",
            "params": {},
            "acceptance": "CANDIDATE ONLY: landing/UI page, not an independently verified historical export",
            "early_recent_evidence": [],
        },
        {
            "mechanism_id": "official_data_interface_service",
            "official_identity": "ChinaMoney/CFETS official data-interface service",
            "url": "https://www.chinamoney.com.cn/chinese/dataInterfaceService/",
            "method": "GET",
            "params": {},
            "acceptance": "CANDIDATE ONLY: official service describes authorized XML/CSV access; no public historical DR/R response was verified",
            "early_recent_evidence": [],
        },
    ]


def count_independent_cfets_paths(records: list[dict[str, Any]]) -> int:
    """Count mechanisms, excluding date/indexType retries of one endpoint."""
    keys = set()
    for record in records:
        params = {
            key: value
            for key, value in record.get("params", {}).items()
            if key not in {"searchDate", "indexType"}
        }
        keys.add((record.get("url"), record.get("method"), tuple(sorted(params.items()))))
    return len(keys)


def run_full_history(
    *, output_root: Path, contract_path: Path, calendar_path: Path, start: str, end: str
) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    output_root.mkdir(parents=True, exist_ok=True)
    calendar = _calendar_evidence(output_root, calendar_path, start, end)
    captured: list[dict[str, Any]] = []
    quarantines: list[str] = []
    event_details: dict[str, list[dict[str, Any]]] = {"omo": [], "mlf": []}
    frames: list[pd.DataFrame] = []
    discovery: dict[str, Any] = {}

    omo_url = contract["sources"]["pboc_omo_release"]["index_url"]
    try:
        first_payload, first_snapshot = _capture_index(output_root, "pboc_omo_release_index", omo_url)
        captured.append({"kind": "index", "source_id": "pboc_omo_release_index", "url": omo_url, "snapshot": snapshot_as_dict(first_snapshot), "status": 200})
        page_urls = _page_urls(first_payload, omo_url)
        index_payloads = [first_payload]
        index_snapshots = [first_snapshot]
        for page_url in page_urls[1:]:
            payload, snapshot = _capture_index(output_root, "pboc_omo_release_index", page_url)
            index_payloads.append(payload)
            index_snapshots.append(snapshot)
            captured.append({"kind": "index", "source_id": "pboc_omo_release_index", "url": page_url, "snapshot": snapshot_as_dict(snapshot), "status": 200})
        omo_items = _omo_announcements(index_payloads, page_urls)
        discovery["omo"] = {"index_pages": len(page_urls), "index_snapshots": [item.sha256 for item in index_snapshots], "relevant_pages": len(omo_items)}
    except Exception as exc:
        detail = {"status": "INDEX_QUARANTINED", "url": omo_url, "reason": f"{type(exc).__name__}: {exc}"}
        qpath = _quarantine_request(output_root, "pboc_full_omo_index", detail)
        quarantines.append(qpath)
        event_details["omo"].append({**detail, "quarantine": qpath})
        omo_items = []
        discovery["omo"] = {"index_pages": 0, "relevant_pages": 0, "status": "INDEX_QUARANTINED"}

    try:
        mlf_items, search_captured = _mlf_search_pages(output_root)
        captured.extend(search_captured)
        discovery["mlf"] = {"search_pages": len(search_captured), "relevant_pages": len(mlf_items), "status": "DISCOVERED"}
    except Exception as exc:
        detail = {"status": "INDEX_QUARANTINED", "url": SEARCH_URL, "reason": f"{type(exc).__name__}: {exc}"}
        qpath = _quarantine_request(output_root, "pboc_full_mlf_search", detail)
        quarantines.append(qpath)
        event_details["mlf"].append({**detail, "quarantine": qpath})
        mlf_items = []
        discovery["mlf"] = {"search_pages": 0, "relevant_pages": 0, "status": "INDEX_QUARANTINED"}

    for kind, items in (("omo", omo_items), ("mlf", mlf_items)):
        # Serial capture avoids same-second manifest-name collisions and keeps
        # immutable raw evidence deterministic across reruns.
        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = [executor.submit(_fetch_and_parse, output_root, kind, item) for item in items]
            for future in as_completed(futures):
                detail, frame = future.result()
                event_details[kind].append(detail)
                if detail.get("quarantine"):
                    quarantines.append(str(detail["quarantine"]))
                if frame is not None and not frame.empty:
                    frames.append(frame)
        event_details[kind].sort(key=lambda item: item.get("url", ""))

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CANONICAL_COLUMNS)
    if not combined.empty:
        combined = combined.drop_duplicates(["series_id", "reference_period", "vintage_id"]).sort_values(["reference_period", "series_id"]).reset_index(drop=True)
        destination = output_root / "curated" / "pboc_omo_mlf_full_history.parquet"
        write_normalized_snapshot(combined, destination)
    omissions = [item for details in event_details.values() for detail in details for item in detail.get("omissions", [])]
    mlf_rate_rows = int(((combined["series_id"] == "CN.PBOC.MLF.1Y.RATE") & (combined["reference_period"] >= "2025-03-01")).sum()) if not combined.empty else 0
    duplicate_keys = int(combined.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not combined.empty else 0
    parse_rates = {
        kind: (sum(item.get("status") == "PARSED" for item in details) / len(details) if details else None)
        for kind, details in event_details.items()
    }
    unexplained = [
        {"kind": kind, **item}
        for kind, details in event_details.items()
        for item in details
        if item.get("status") not in {"PARSED"}
    ]
    cfets_paths = _cfets_evidence(output_root, output_root / "audits" / "w1_rates_shadow.json")
    audit = {
        "scope": {"start": start, "end": end, "four_series_only": True, "research_ready": False},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calendar": calendar,
        "pboc": {
            "discovery": discovery,
            "parse_counts": {kind: sum(item.get("status") == "PARSED" for item in details) for kind, details in event_details.items()},
            "parse_rates": parse_rates,
            "events": event_details,
            "structural_omissions": [item for item in omissions if item.get("state") == "UNIFIED_RATE_STRUCTURALLY_UNDEFINED"],
            "mlf_post_2025_03_rate_rows": mlf_rate_rows,
        },
        "cfets": {"independent_mechanisms": cfets_paths, "independent_mechanism_count": count_independent_cfets_paths(cfets_paths), "formal_backfill": False, "calendar_blocked": calendar.get("status") != "OK"},
        "normalized": {"rows": len(combined), "duplicate_primary_keys": duplicate_keys, "raw_hashes_valid": all(re.fullmatch(r"[0-9a-f]{64}", item["snapshot"]["sha256"]) for item in captured if "snapshot" in item)},
        "quarantine": quarantines,
        "unexplained": unexplained + ([{"kind": "calendar", **calendar}] if calendar.get("status") != "OK" else []),
        "captured": captured,
        "blocked": True,
        "research_ready": False,
    }
    _write_json(output_root / "audits" / "w1_rates_full_history.json", audit)
    (output_root / "audits" / "w1_rates_full_history_summary.md").write_text(
        "# R011 full-history source summary\n\n"
        f"PBOC OMO discovered {discovery.get('omo', {}).get('relevant_pages', 0)} relevant announcement pages across {discovery.get('omo', {}).get('index_pages', 0)} index pages; parse rate={parse_rates['omo']}.\n\n"
        f"PBOC MLF official search discovered {discovery.get('mlf', {}).get('relevant_pages', 0)} candidate pages across {discovery.get('mlf', {}).get('search_pages', 0)} search pages; parse rate={parse_rates['mlf']}; post-2025-03 MLF rate rows={mlf_rate_rows}.\n\n"
        f"CFETS remains blocked: calendar status={calendar.get('status')}; three distinct official mechanisms are recorded as evidence only and no CFETS values were promoted to curated.\n\n"
        "No forward-fill, interpolation, old MLF rate continuation, fixing rate, or third-party value was used. Research-ready promotion is prohibited.\n",
        encoding="utf-8",
    )
    state_dir = output_root / "state" / "w1_rates_luna_full"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "BLOCKED.md").write_text(
        "# R011 full-history BLOCKED\n\n"
        "Status is intentionally blocked and `research_ready=false`.\n\n"
        f"- CFETS real strategy calendar: `{calendar.get('status')}`; {calendar.get('error', 'not supplied')}.\n"
        f"- CFETS formal history: not promoted; three independent official mechanism records are in `audits/w1_rates_full_history.json`.\n"
        f"- PBOC unexplained items: {len(unexplained)}; see full audit and quarantine paths.\n"
        "- No third-party data was used.\n",
        encoding="utf-8",
    )
    (state_dir / "PROGRESS.md").write_text(
        "# R011 W1 rates full-history progress\n\n"
        f"- Task 0: passed; Gold exact and W1 baseline 13 passed with worktree basetemp.\n"
        f"- Calendar: {calendar.get('status')}; CFETS remains blocked.\n"
        f"- PBOC OMO: discovered {discovery.get('omo', {}).get('relevant_pages', 0)} pages; parsed {parse_rates['omo']}.\n"
        f"- PBOC MLF: discovered {discovery.get('mlf', {}).get('relevant_pages', 0)} candidate pages; parsed {parse_rates['mlf']}; post-2025-03 rate rows={mlf_rate_rows}.\n"
        f"- Full audit: `audits/w1_rates_full_history.json`; summary: `audits/w1_rates_full_history_summary.md`.\n"
        f"- Blocked status: true; unexplained items={len(audit['unexplained'])}; no strategy integration.\n",
        encoding="utf-8",
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=Path("config/macro_w1_rates_contract.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/macro_r011"))
    parser.add_argument("--calendar-source", type=Path, required=True)
    parser.add_argument("--start", default="2026-07-27")
    parser.add_argument("--end", default="2026-08-25")
    args = parser.parse_args()
    audit = run_full_history(
        output_root=args.output_root,
        contract_path=args.contract,
        calendar_path=args.calendar_source,
        start=args.start,
        end=args.end,
    )
    print(json.dumps({"blocked": audit["blocked"], "research_ready": audit["research_ready"], "pboc": audit["pboc"]["discovery"], "calendar": audit["calendar"]}, ensure_ascii=False, indent=2))
    return 2 if audit["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
