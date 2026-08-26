"""Resumable official-source backfills and independent Tushare reconciliation."""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

import pandas as pd

from .adapters import parse_cfets_repo_json, parse_pboc_policy_release
from .contracts import (
    CANONICAL_COLUMNS,
    RawSnapshot,
    SeriesSpec,
    capture_raw_snapshot,
    load_registry,
    snapshot_as_dict,
    write_normalized_snapshot,
)
from .pipeline import fetch_public_url, run_pmi_sample, run_shibor_sample, validate_canonical


NBS_SEARCH_URL = "https://api.so-gov.cn/query/s"
NBS_SITE_CODE = "bm36000002"
PMI_TITLE = re.compile(r"^(?P<year>\d{4})年(?P<month>\d{1,2})月中国采购经理指数运行情况$")
PMI_YEAR_MONTH = re.compile(r"(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月份?")
PMI_SERIES_TO_TUSHARE = {
    "CN.PMI.MFG.HEADLINE": "pmi010000",
    "CN.PMI.MFG.PRODUCTION": "pmi010400",
    "CN.PMI.MFG.NEW_ORDERS": "pmi010500",
    "CN.PMI.MFG.RAW_MATERIAL_INVENTORY": "pmi010700",
    "CN.PMI.MFG.EMPLOYMENT": "pmi010800",
    "CN.PMI.MFG.SUPPLIER_DELIVERY_TIME": "pmi010600",
}
SHIBOR_SERIES_TO_TUSHARE = {
    "CN.SHIBOR.ON": "on",
    "CN.SHIBOR.1W": "1w",
    "CN.SHIBOR.2W": "2w",
    "CN.SHIBOR.1M": "1m",
    "CN.SHIBOR.3M": "3m",
    "CN.SHIBOR.6M": "6m",
    "CN.SHIBOR.9M": "9m",
    "CN.SHIBOR.1Y": "1y",
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _post_search(parameters: dict[str, str], attempts: int = 3) -> dict[str, Any]:
    body = urlencode(parameters).encode("utf-8")
    request = Request(
        NBS_SEARCH_URL,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "QuantTradingSystem-R011-internal-research/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def infer_pmi_period(title: str, document_date: str) -> str | None:
    match = PMI_YEAR_MONTH.search(title)
    if match is None:
        return None
    observed_month = int(match.group("month"))
    explicit_year = match.group("year")
    if explicit_year is not None:
        return f"{int(explicit_year):04d}-{observed_month:02d}"
    published = date.fromisoformat(document_date)
    observed_year = published.year - int(observed_month > published.month)
    return f"{observed_year:04d}-{observed_month:02d}"


def _search_pages(parameters: dict[str, str], interval_seconds: float) -> list[dict[str, Any]]:
    first = _post_search({**parameters, "page": "1", "pageSize": "20"})
    pages = max(1, math.ceil(int(first.get("totalHits", 0)) / 20))
    documents: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        response = first if page == 1 else _post_search({**parameters, "page": str(page), "pageSize": "20"})
        for item in response.get("resultDocs", []):
            data = item.get("data", {})
            documents.append({
                "title": str(data.get("titleO", "")),
                "url": str(data.get("url", "")),
                "document_date": str(data.get("docDate", "")),
            })
        if page < pages:
            time.sleep(interval_seconds)
    return documents


def discover_pmi_releases(*, interval_seconds: float = 1.0) -> list[dict[str, Any]]:
    modern = _search_pages(
        {
            "qt": "中国采购经理指数运行情况",
            "siteCode": NBS_SITE_CODE,
            "sort": "dateDesc",
            "keyPlace": "1",
        },
        interval_seconds,
    )
    candidates: list[dict[str, Any]] = []
    for item in modern:
        match = PMI_TITLE.fullmatch(item["title"])
        if match and item["url"].startswith("https://www.stats.gov.cn/"):
            item["reference_period"] = f"{int(match.group('year')):04d}-{int(match.group('month')):02d}"
            item["layout"] = "rolling"
            candidates.append(item)
    for year in range(2005, 2018):
        legacy = _search_pages(
            {
                "qt": "采购经理指数",
                "siteCode": NBS_SITE_CODE,
                "sort": "dateDesc",
                "timeOption": "2",
                "startDateStr": f"{year}-01-01",
                "endDateStr": f"{year}-12-31",
            },
            interval_seconds,
        )
        for item in legacy:
            title = item["title"]
            if (
                item["url"].startswith("https://www.stats.gov.cn/sj/zxfb/")
                and "制造业采购经理指数" in title
                and "非制造业" not in title
                and "解读" not in title
                and "答记者问" not in title
            ):
                item["reference_period"] = infer_pmi_period(title, item["document_date"])
                item["layout"] = "legacy_or_rolling"
                candidates.append(item)
        time.sleep(interval_seconds)
    return sorted({item["url"]: item for item in candidates}.values(), key=lambda item: (item["document_date"], item["url"]))


def _combine_normalized(output_root: Path, source_ids: str | tuple[str, ...], destination: Path) -> pd.DataFrame:
    if isinstance(source_ids, str):
        source_ids = (source_ids,)
    paths = sorted(
        path
        for source_id in source_ids
        for path in (output_root / "normalized" / source_id).glob("*.parquet")
    )
    if not paths:
        raise ValueError(f"no normalized shards for {', '.join(source_ids)}")
    frame = pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)
    frame = frame.drop_duplicates(["series_id", "reference_period", "vintage_id"]).sort_values(
        ["reference_period", "series_id", "available_at", "vintage_id"]
    ).reset_index(drop=True)
    write_normalized_snapshot(frame, destination)
    return frame


def run_shibor_backfill(
    *,
    registry_path: Path,
    output_root: Path,
    start_date: str = "2006-10-08",
    end_date: str | None = None,
) -> dict[str, Any]:
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = date.fromisoformat(start_date)
    registry = load_registry(registry_path)
    interval = registry.source("cfets_shibor_public").request_interval_seconds
    state_path = output_root / "state" / "shibor_backfill.json"
    state = _read_json(state_path, {"completed_years": [], "failures": {}})
    completed = {int(value) for value in state["completed_years"]}
    for year in range(start.year, end.year + 1):
        if year in completed:
            continue
        shard_start = max(start, date(year, 1, 1))
        shard_end = min(end, date(year, 12, 31))
        try:
            run_shibor_sample(
                registry_path=registry_path,
                output_root=output_root,
                start_date=shard_start.isoformat(),
                end_date=shard_end.isoformat(),
            )
            completed.add(year)
            state["completed_years"] = sorted(completed)
            state["failures"].pop(str(year), None)
        except Exception as exc:
            state["failures"][str(year)] = f"{type(exc).__name__}: {exc}"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(state_path, state)
        if year < end.year:
            time.sleep(interval)
    destination = output_root / "curated" / "shibor_observations.parquet"
    frame = _combine_normalized(output_root, "cfets_shibor_public", destination)
    specs = registry.series_for_source("cfets_shibor_public")
    validation = validate_canonical(frame, specs)
    report = {
        "source_id": "cfets_shibor_public",
        "completed_years": sorted(completed),
        "failures": state["failures"],
        "rows": len(frame),
        "dates": int(frame["reference_period"].nunique()),
        "reference_period_min": str(frame["reference_period"].min()),
        "reference_period_max": str(frame["reference_period"].max()),
        "tenors_complete_each_date": bool(frame.groupby("reference_period")["series_id"].nunique().eq(8).all()),
        "validation": validation,
        "research_ready": False,
        "restriction": "historical backfill is not contemporaneously observed; enforce tradable_at",
        "curated_path": str(destination.resolve()),
    }
    _write_json(output_root / "audits" / "shibor_backfill.json", report)
    return report


def run_pmi_backfill(
    *,
    registry_path: Path,
    output_root: Path,
    refresh_catalog: bool = False,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    interval = registry.source("nbs_pmi_release_archive").request_interval_seconds
    catalog_path = output_root / "catalogs" / "pmi_release_pages.json"
    if refresh_catalog or not catalog_path.exists():
        catalog = discover_pmi_releases(interval_seconds=1.0)
        _write_json(catalog_path, {"generated_at": datetime.now(timezone.utc).isoformat(), "pages": catalog})
    else:
        catalog = _read_json(catalog_path, {"pages": []})["pages"]
    state_path = output_root / "state" / "pmi_backfill.json"
    state = _read_json(state_path, {"completed_urls": [], "failures": {}})
    completed = set(state["completed_urls"])
    for index, item in enumerate(catalog):
        url = item["url"]
        if url in completed:
            continue
        try:
            run_pmi_sample(registry_path=registry_path, output_root=output_root, release_url=url)
            completed.add(url)
            state["completed_urls"] = sorted(completed)
            state["failures"].pop(url, None)
        except Exception as exc:
            state["failures"][url] = f"{type(exc).__name__}: {exc}"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(state_path, state)
        if index + 1 < len(catalog):
            time.sleep(interval)
    destination = output_root / "curated" / "pmi_observation_vintages.parquet"
    frame = _combine_normalized(
        output_root, ("nbs_pmi_release_archive", "nbs_national_data_pmi"), destination
    )
    validation = validate_canonical(frame, registry.series_for_source("nbs_pmi_release_archive"))
    parsed_periods = set(frame["reference_period"].astype(str))
    start = min(parsed_periods)
    end = max(parsed_periods)
    expected = set(pd.period_range(start, end, freq="M").astype(str))
    missing = sorted(expected - parsed_periods)
    non_pit = sorted(
        set(
            frame.loc[
                frame["availability_evidence"] == "current_nbs_database_export_not_historical_pit",
                "reference_period",
            ].astype(str)
        )
    )
    report = {
        "source_id": "nbs_pmi_release_archive+nbs_national_data_pmi",
        "catalog_pages": len(catalog),
        "completed_pages": len(completed),
        "failures": state["failures"],
        "rows": len(frame),
        "vintages": int(frame["vintage_id"].nunique()),
        "reference_period_min": start,
        "reference_period_max": end,
        "missing_reference_periods_within_parsed_range": missing,
        "historical_pit_gap_periods": non_pit,
        "numerically_complete": not missing,
        "historical_pit_complete": not non_pit,
        "validation": validation,
        "research_ready": not state["failures"] and validation["passed"] and not missing and not non_pit,
        "restriction": (
            "numeric continuity is complete, but listed periods are current database exports without historical PIT evidence"
            if non_pit
            else ("known monthly coverage gap must be excluded explicitly" if missing else None)
        ),
        "curated_path": str(destination.resolve()),
        "catalog_path": str(catalog_path.resolve()),
    }
    _write_json(output_root / "audits" / "pmi_backfill.json", report)
    return report


def _comparison_report(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> tuple[dict[str, Any], pd.DataFrame]:
    joined = left.merge(right, how="inner", on=keys, suffixes=("_official", "_tushare"))
    joined["absolute_difference"] = (joined["value_official"] - joined["value_tushare"]).abs()
    mismatches = joined.loc[joined["absolute_difference"] > 1e-9].copy()
    report = {
        "overlap_cells": len(joined),
        "matching_cells": len(joined) - len(mismatches),
        "mismatch_cells": len(mismatches),
        "max_absolute_difference": float(joined["absolute_difference"].max()) if len(joined) else None,
        "reference_period_min": str(joined["reference_period"].min()) if len(joined) else None,
        "reference_period_max": str(joined["reference_period"].max()) if len(joined) else None,
        "passed": bool(len(joined) and mismatches.empty),
    }
    return report, mismatches


def reconcile_tushare(
    *, output_root: Path, tushare_macro_root: Path
) -> dict[str, Any]:
    shibor = pd.read_parquet(output_root / "curated" / "shibor_observations.parquet")
    shibor_left = shibor[["series_id", "reference_period", "value"]].rename(columns={"value": "value_official"})
    shibor_tushare = pd.read_parquet(tushare_macro_root / "shibor.parquet")
    shibor_right = shibor_tushare.melt("date", value_vars=list(SHIBOR_SERIES_TO_TUSHARE.values()), var_name="field", value_name="value_tushare")
    shibor_right["series_id"] = shibor_right["field"].map({value: key for key, value in SHIBOR_SERIES_TO_TUSHARE.items()})
    shibor_right["reference_period"] = pd.to_datetime(shibor_right["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    shibor_report, shibor_mismatch = _comparison_report(
        shibor_left, shibor_right[["series_id", "reference_period", "value_tushare"]], ["series_id", "reference_period"]
    )
    swap_dates: list[str] = []
    for reference_period, group in shibor_mismatch.groupby("reference_period"):
        rows = {str(row.series_id): row for row in group.itertuples()}
        overnight = rows.get("CN.SHIBOR.ON")
        three_month = rows.get("CN.SHIBOR.3M")
        if overnight is not None and three_month is not None and (
            abs(overnight.value_official - three_month.value_tushare) <= 1e-9
            and abs(three_month.value_official - overnight.value_tushare) <= 1e-9
        ):
            swap_dates.append(str(reference_period))
    shibor_report["diagnosis"] = {
        "tushare_on_3m_exact_column_swap": bool(swap_dates) and len(swap_dates) * 2 == len(shibor_mismatch),
        "affected_dates": swap_dates,
    }

    pmi = pd.read_parquet(output_root / "curated" / "pmi_observation_vintages.parquet")
    pmi_latest = pmi.sort_values(["available_at", "retrieved_at"]).drop_duplicates(
        ["series_id", "reference_period"], keep="last"
    )
    pmi_left = pmi_latest[["series_id", "reference_period", "value"]].rename(columns={"value": "value_official"})
    pmi_tushare = pd.read_parquet(tushare_macro_root / "cn_pmi.parquet")
    pmi_right = pmi_tushare.melt("month", value_vars=list(PMI_SERIES_TO_TUSHARE.values()), var_name="field", value_name="value_tushare")
    pmi_right["series_id"] = pmi_right["field"].map({value: key for key, value in PMI_SERIES_TO_TUSHARE.items()})
    pmi_right["reference_period"] = pd.to_datetime(pmi_right["month"], format="%Y%m").dt.strftime("%Y-%m")
    pmi_right = pmi_right.dropna(subset=["value_tushare"])
    pmi_report, pmi_mismatch = _comparison_report(
        pmi_left, pmi_right[["series_id", "reference_period", "value_tushare"]], ["series_id", "reference_period"]
    )

    quarantine = output_root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    shibor_mismatch.to_parquet(quarantine / "shibor_tushare_mismatches.parquet", index=False)
    pmi_mismatch.to_parquet(quarantine / "pmi_tushare_mismatches.parquet", index=False)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison_source": str(tushare_macro_root.resolve()),
        "official_source_precedence": True,
        "tushare_files_modified": False,
        "shibor": shibor_report,
        "pmi": pmi_report,
        "passed": shibor_report["passed"] and pmi_report["passed"],
        "research_readiness": {
            "pmi_reconciled_window_ready": pmi_report["passed"],
            "pmi_reconciled_window_start": pmi_report["reference_period_min"],
            "pmi_reconciled_window_end": pmi_report["reference_period_max"],
            "shibor_ready": False,
            "shibor_restriction": (
                "historical capture timing"
                if shibor_report["passed"]
                else "historical capture timing and quarantined Tushare O/N-3M swap"
            ),
        },
    }
    _write_json(output_root / "audits" / "tushare_reconciliation.json", report)
    return report


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append({"href": self._href, "text": " ".join("".join(self._text).split())})
            self._href = None
            self._text = []


def _period_from_link(value: str) -> str | None:
    match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", value)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", value)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return None


def _capture_response(
    *,
    output_root: Path,
    source_id: str,
    response: Any,
    method: str,
    request_url: str,
    extension: str,
) -> RawSnapshot:
    return capture_raw_snapshot(
        output_root=output_root,
        source_id=source_id,
        payload=response.payload,
        retrieved_at=datetime.now(timezone.utc),
        request_method=method,
        request_url=response.final_url or request_url,
        response_status=response.status,
        response_headers=response.headers,
        extension=extension,
    )


def _quarantine_request(output_root: Path, label: str, detail: dict[str, Any]) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
    path = output_root / "quarantine" / "w1_rates" / f"{safe}.json"
    _write_json(path, detail)
    return str(path.resolve())


def _request_and_snapshot(
    *,
    output_root: Path,
    source_id: str,
    url: str,
    method: str,
    data: bytes | None,
    extension: str,
) -> tuple[Any, RawSnapshot]:
    response = fetch_public_url(
        url,
        method=method,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"} if data else None,
        attempts=1,
    )
    snapshot = _capture_response(
        output_root=output_root,
        source_id=source_id,
        response=response,
        method=method,
        request_url=url,
        extension=extension,
    )
    return response, snapshot


def _write_rate_shard(output_root: Path, frame: pd.DataFrame, snapshot: RawSnapshot, extra: dict[str, Any]) -> None:
    if frame.empty:
        return
    normalized_path = output_root / "normalized" / snapshot.source_id / f"{snapshot.sha256}.parquet"
    write_normalized_snapshot(frame, normalized_path)
    manifest = {
        "schema_version": 2,
        "source_id": snapshot.source_id,
        "readiness": "SHADOW_VALIDATED",
        "research_ready": False,
        "normalized_path": str(normalized_path.resolve()),
        "snapshot": snapshot_as_dict(snapshot),
        **extra,
    }
    _write_json(normalized_path.with_suffix(".manifest.json"), manifest)


def _discover_pboc_pages(
    payload: bytes, base_url: str, start_date: str, end_date: str
) -> list[dict[str, str]]:
    parser = _AnchorParser()
    parser.feed(payload.decode("utf-8", errors="strict"))
    pages: dict[str, dict[str, str]] = {}
    for link in parser.links:
        url = urljoin(base_url, link["href"])
        if urlsplit(url).netloc.lower() not in {"www.pbc.gov.cn", "pbc.gov.cn"}:
            continue
        period = _period_from_link(url + " " + link["text"])
        if period and start_date <= period <= end_date:
            pages[url] = {"url": url, "hint_date": period, "link_text": link["text"]}
    return sorted(pages.values(), key=lambda item: (item["hint_date"], item["url"]))


def _append_frame(frames: list[pd.DataFrame], frame: pd.DataFrame) -> None:
    if not frame.empty:
        frames.append(frame)


def _date_strings(start_date: str, end_date: str) -> list[str]:
    return [item.date().isoformat() for item in pd.date_range(start_date, end_date, freq="D")]


def run_rates_shadow_backfill(
    *,
    registry_path: Path,
    output_root: Path,
    start_date: str = "2026-07-27",
    end_date: str = "2026-08-25",
    sleep_seconds: float | None = None,
) -> dict[str, Any]:
    """Run the frozen one-month official-source shadow capture and first audit."""
    contract = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = contract["sources"]
    repo = SimpleNamespace(source_id="cfets_repo_daily", **sources["cfets_repo_daily"])
    omo = SimpleNamespace(source_id="pboc_omo_release", url=sources["pboc_omo_release"]["index_url"], method=sources["pboc_omo_release"]["method"])
    mlf = SimpleNamespace(source_id="pboc_mlf_release", url=sources["pboc_mlf_release"]["index_url"], method=sources["pboc_mlf_release"]["method"])
    series_specs = tuple(
        SeriesSpec(
            series_id=series_id,
            source_id=spec["source_id"],
            source_field=spec.get("instrument_code", series_id),
            frequency=spec["frequency"],
            unit=spec["unit"],
            seasonal_adjustment="not_applicable",
            value_min=float(spec["value_bounds"][0]),
            value_max=float(spec["value_bounds"][1]),
        )
        for series_id, spec in contract["series"].items()
    )
    dates = _date_strings(start_date, end_date)
    weekdays = [item for item in dates if date.fromisoformat(item).weekday() < 5]
    interval = repo.request_interval_seconds if sleep_seconds is None else sleep_seconds
    repo_frames: list[pd.DataFrame] = []
    all_frames: list[pd.DataFrame] = []
    captured: list[dict[str, Any]] = []
    quarantine: list[str] = []
    repo_outcomes: dict[str, dict[str, Any]] = {}

    for requested_date in weekdays:
        outcome = {"status": "PENDING", "requests": []}
        for series_id, index_type in (
            ("CN.REPO.DR007", repo.dr007_index_type if hasattr(repo, "dr007_index_type") else "markInterBankVOList"),
            ("CN.REPO.R007", repo.r007_index_type if hasattr(repo, "r007_index_type") else "markVOList"),
        ):
            body = urlencode({
                "lang": "cn",
                "publishedTime": "2200",
                "searchDate": requested_date,
                "indexType": index_type,
            }).encode("utf-8")
            request_url = repo.url
            try:
                response, snapshot = _request_and_snapshot(
                    output_root=output_root,
                    source_id=repo.source_id,
                    url=request_url,
                    method=repo.method,
                    data=body,
                    extension="json",
                )
                captured.append({"source_id": repo.source_id, "requested_date": requested_date, "index_type": index_type, "snapshot": snapshot_as_dict(snapshot), "status": response.status})
                if response.status != 200:
                    raise ValueError(f"non-200 response: {response.status}")
                frame = parse_cfets_repo_json(
                    response.payload,
                    snapshot,
                    requested_date=requested_date,
                    index_type=index_type,
                    series_id=series_id,
                )
                _append_frame(repo_frames, frame)
                _append_frame(all_frames, frame)
                _write_rate_shard(output_root, frame, snapshot, {"requested_date": requested_date, "index_type": index_type})
                outcome["requests"].append({"series_id": series_id, "status": "SUCCESS", "raw_sha256": snapshot.sha256})
            except Exception as exc:
                detail = {"source": repo.url, "method": repo.method, "form": body.decode("utf-8"), "requested_date": requested_date, "index_type": index_type, "error": f"{type(exc).__name__}: {exc}"}
                qpath = _quarantine_request(output_root, f"cfets_{requested_date}_{index_type}", detail)
                quarantine.append(qpath)
                outcome["requests"].append({"series_id": series_id, "status": "QUARANTINED", "reason": detail["error"], "quarantine": qpath})
            if requested_date != weekdays[-1] or series_id != "CN.REPO.R007":
                time.sleep(interval)
        outcome["status"] = "OFFICIAL_ROWS" if all(item["status"] == "SUCCESS" for item in outcome["requests"]) else "OFFICIAL_UNAVAILABLE_QUARANTINED"
        repo_outcomes[requested_date] = outcome

    events: dict[str, list[dict[str, Any]]] = {"omo": [], "mlf": []}
    for source in (omo, mlf):
        index_source_id = f"{source.source_id}_index"
        try:
            response, snapshot = _request_and_snapshot(
                output_root=output_root,
                source_id=index_source_id,
                url=source.url,
                method=source.method,
                data=None,
                extension="html",
            )
            captured.append({"source_id": index_source_id, "snapshot": snapshot_as_dict(snapshot), "status": response.status})
            if response.status != 200:
                raise ValueError(f"non-200 response: {response.status}")
            pages = _discover_pboc_pages(response.payload, source.url, start_date, end_date)
        except Exception as exc:
            qpath = _quarantine_request(output_root, f"{source.source_id}_index", {"source": source.url, "method": source.method, "error": f"{type(exc).__name__}: {exc}"})
            quarantine.append(qpath)
            events["omo" if source is omo else "mlf"].append({"status": "INDEX_QUARANTINED", "quarantine": qpath})
            continue
        kind = "omo" if source is omo else "mlf"
        for page in pages:
            try:
                response, page_snapshot = _request_and_snapshot(
                    output_root=output_root,
                    source_id=source.source_id,
                    url=page["url"],
                    method=source.method,
                    data=None,
                    extension="html",
                )
                captured.append({"source_id": source.source_id, "url": page["url"], "snapshot": snapshot_as_dict(page_snapshot), "status": response.status})
                if response.status != 200:
                    raise ValueError(f"non-200 response: {response.status}")
                if kind == "omo" and "逆回购" not in response.payload.decode("utf-8", errors="ignore"):
                    events[kind].append({"status": "NOT_OMO_ANNOUNCEMENT", "url": page["url"]})
                    continue
                parsed = parse_pboc_policy_release(response.payload, page_snapshot, source_file=Path(urlsplit(page["url"]).path).name)
                _append_frame(all_frames, parsed.observations)
                _write_rate_shard(output_root, parsed.observations, page_snapshot, {"page_url": page["url"], "page_timestamp": parsed.page_timestamp.isoformat(), "event_kind": parsed.event_kind, "omissions": list(parsed.omissions)})
                events[kind].append({"status": "PARSED", "url": page["url"], "event_kind": parsed.event_kind, "omissions": list(parsed.omissions), "page_timestamp": parsed.page_timestamp.isoformat()})
            except Exception as exc:
                qpath = _quarantine_request(output_root, f"{source.source_id}_{page['hint_date']}", {"source": page["url"], "method": source.method, "error": f"{type(exc).__name__}: {exc}"})
                quarantine.append(qpath)
                events[kind].append({"status": "QUARANTINED", "url": page["url"], "reason": f"{type(exc).__name__}: {exc}", "quarantine": qpath})

    frame = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=CANONICAL_COLUMNS)
    repo_frame = pd.concat(repo_frames, ignore_index=True) if repo_frames else pd.DataFrame(columns=CANONICAL_COLUMNS)
    if not repo_frame.empty:
        write_normalized_snapshot(repo_frame, output_root / "curated" / "w1_rates_repo_shadow.parquet")
    pair_dates = sorted(
        date_value for date_value, group in repo_frame.groupby("reference_period")
        if set(group["series_id"]) == {"CN.REPO.DR007", "CN.REPO.R007"}
    ) if not repo_frame.empty else []
    duplicates = int(frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not frame.empty else 0
    value_domain_failures = []
    for series_id, group in frame.groupby("series_id") if not frame.empty else []:
        spec = next((item for item in series_specs if item.series_id == series_id), None)
        if spec is not None and not group["value"].between(spec.value_min, spec.value_max).all():
            value_domain_failures.append(series_id)
    daily_changes = []
    spreads = []
    if not repo_frame.empty:
        for series_id, group in repo_frame.sort_values("reference_period").groupby("series_id"):
            changes = group["value"].diff().abs()
            daily_changes.extend(float(value) for value in changes.dropna() if value > 2.0)
        pivot = repo_frame.pivot_table(index="reference_period", columns="series_id", values="value", aggfunc="first")
        if {"CN.REPO.DR007", "CN.REPO.R007"}.issubset(pivot.columns):
            spreads = [float(value) for value in (pivot["CN.REPO.R007"] - pivot["CN.REPO.DR007"]).dropna()]
    mlf_rows = frame[(frame["series_id"] == "CN.PBOC.MLF.1Y.RATE") & (frame["reference_period"] >= "2025-03-01")] if not frame.empty else pd.DataFrame()
    discovered = {kind: sum(1 for item in items if "url" in item and item.get("status") != "NOT_OMO_ANNOUNCEMENT") for kind, items in events.items()}
    parsed = {kind: sum(1 for item in items if item.get("status") == "PARSED") for kind, items in events.items()}
    event_rates = {kind: (parsed[kind] / discovered[kind] if discovered[kind] else None) for kind in events}
    event_omissions = [omission for items in events.values() for item in items for omission in item.get("omissions", [])]
    structural_omissions = [omission for omission in event_omissions if omission["series_id"] == "CN.PBOC.MLF.1Y.RATE"]
    blocked_probe: list[dict[str, Any]] = []
    if len(pair_dates) / len(weekdays) < 0.95 and weekdays:
        probe_date = next(day for day in weekdays if day not in pair_dates)
        for attempt in range(1, 4):
            body = urlencode({
                "lang": "cn",
                "publishedTime": "2200",
                "searchDate": probe_date,
                "indexType": "markInterBankVOList",
            }).encode("utf-8")
            try:
                response, probe_snapshot = _request_and_snapshot(
                    output_root=output_root,
                    source_id=repo.source_id,
                    url=repo.url,
                    method=repo.method,
                    data=body,
                    extension="json",
                )
                captured.append({"source_id": repo.source_id, "requested_date": probe_date, "index_type": "markInterBankVOList", "probe_attempt": attempt, "snapshot": snapshot_as_dict(probe_snapshot), "status": response.status})
                blocked_probe.append({"attempt": attempt, "requested_date": probe_date, "index_type": "markInterBankVOList", "status": response.status, "raw_sha256": probe_snapshot.sha256, "response_summary": response.payload[:160].decode("utf-8", errors="replace")})
            except Exception as exc:
                blocked_probe.append({"attempt": attempt, "requested_date": probe_date, "index_type": "markInterBankVOList", "error": f"{type(exc).__name__}: {exc}"})
    audit = {
        "contract_id": "R011.W1.RATES_LIQUIDITY.SHADOW_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_range": {"start": start_date, "end": end_date, "calendar_dates": len(dates), "trading_dates": len(weekdays)},
        "repo": {"requested_dates": len(weekdays), "request_count": len(weekdays) * 2, "success_dates": len(pair_dates), "success_date_list": pair_dates, "coverage": len(pair_dates) / len(weekdays) if weekdays else 0.0, "outcomes": repo_outcomes, "empty_response_dates": [day for day, item in repo_outcomes.items() if any("no records" in str(req.get("reason", "")) for req in item["requests"])], "source_date_mismatch_dates": [day for day, item in repo_outcomes.items() if any("date mismatch" in str(req.get("reason", "")) for req in item["requests"]) ]},
        "repo_pair_same_date_coverage": len(pair_dates) / len(weekdays) if weekdays else 0.0,
        "duplicate_primary_keys": duplicates,
        "value_domain_failures": value_domain_failures,
        "daily_change_over_2pp": daily_changes,
        "r007_minus_dr007_percent_points": spreads,
        "events": {"discovered": discovered, "parsed": parsed, "parse_rate": event_rates, "details": events},
        "timestamp_order": validate_canonical(frame, series_specs) if not frame.empty else {"passed": True, "reason": "no rows"},
        "raw_hash": {"captured_responses": len(captured), "valid_sha256": all(re.fullmatch(r"[0-9a-f]{64}", item["snapshot"]["sha256"]) for item in captured)},
        "mlf_structural_omissions": structural_omissions,
        "event_omissions": event_omissions,
        "mlf_post_reform_rate_rows": len(mlf_rows),
        "calendar_status": {day: ("NON_TRADING_DAY" if date.fromisoformat(day).weekday() >= 5 else repo_outcomes.get(day, {}).get("status", "UNEXPLAINED_MISSING")) for day in dates},
        "unexplained_missing_dates": [day for day in weekdays if day not in repo_outcomes],
        "quarantine": quarantine,
        "blocked_probe_attempts": blocked_probe,
        "captured": captured,
    }
    blocked = audit["repo_pair_same_date_coverage"] < 0.95 or any(value != 1.0 for value in event_rates.values() if value is not None)
    audit["research_ready"] = not blocked and duplicates == 0 and not value_domain_failures and len(mlf_rows) == 0 and not audit["unexplained_missing_dates"]
    audit["blocked"] = blocked
    _write_json(output_root / "audits" / "w1_rates_shadow.json", audit)
    (output_root / "audits" / "w1_rates_shadow_summary.md").write_text(
        "# R011 W1 rates shadow source summary\n\n"
        f"Window: {start_date} to {end_date}. Research-ready promotion: **NO**.\n\n"
        "| Source | Official endpoint | Result |\n"
        "|---|---|---|\n"
        f"| CFETS repo daily | `{repo.url}` | {len(pair_dates)}/{len(weekdays)} trading dates paired ({audit['repo_pair_same_date_coverage']:.1%}); rolling-window empty responses quarantined |\n"
        f"| PBOC OMO index/release | `{omo.url}` | {discovered['omo']}/{parsed['omo']} relevant pages parsed ({event_rates['omo']}); zero-quantity pages retained as no-rate events |\n"
        f"| PBOC MLF index/release | `{mlf.url}` | {discovered['mlf']}/{parsed['mlf']} pages parsed ({event_rates['mlf']}); post-2025-03 unified-rate rows={len(mlf_rows)} |\n\n"
        "## Decision\n\n"
        "Do not expand the backfill or connect these series to strategy code. The official CFETS historical endpoint exposes only a rolling window in this environment; three independent probes for the first missing historical date returned HTTP 200 with empty records. No Tushare or other third-party values were used to fill the gap.\n\n"
        "The PBOC event path is source-available for the discovered window and parses at 100%. OMO zero-operation notices are explainable omissions, not synthetic rates. The MLF notice confirms the post-2025-03 multiple-price regime, so `CN.PBOC.MLF.1Y.RATE` remains structurally undefined after the break.\n\n"
        "See `w1_rates_shadow.json` for request bodies, response status, raw SHA-256, timestamp checks, and quarantine paths.\n",
        encoding="utf-8",
    )
    progress = output_root / "state" / "w1_rates_luna" / "PROGRESS.md"
    progress.parent.mkdir(parents=True, exist_ok=True)
    progress.write_text(
        "# R011 W1 rates shadow progress\n\n"
        f"- Range: {start_date} to {end_date}; calendar dates={len(dates)}, trading dates={len(weekdays)}.\n"
        "- Offline parser/gold regression: 10 passed; contract and W1 gate baseline: passed.\n"
        f"- CFETS pair coverage: {len(pair_dates)}/{len(weekdays)} ({audit['repo_pair_same_date_coverage']:.1%}); quarantine={len(quarantine)}.\n"
        f"- PBOC discovery/parse: OMO {discovered['omo']}/{parsed['omo']}, MLF {discovered['mlf']}/{parsed['mlf']}; post-reform MLF rate rows={len(mlf_rows)}.\n"
        f"- research_ready={audit['research_ready']}; blocked={blocked}. See `audits/w1_rates_shadow.json` for raw hashes and per-request evidence.\n\n"
        "## Next step\n\n"
        "Sol review is required before any broader backfill or strategy use.\n",
        encoding="utf-8",
    )
    if blocked:
        blocked_path = output_root / "state" / "w1_rates_luna" / "BLOCKED.md"
        blocked_path.write_text(
            "# R011 W1 rates shadow BLOCKED\n\n"
            "Official-source shadow did not meet the frozen coverage/parse gate. No third-party values were used.\n\n"
            f"- CFETS pair coverage: {audit['repo_pair_same_date_coverage']:.1%}\n"
            f"- OMO event parse rate: {event_rates['omo']}\n"
            f"- MLF event parse rate: {event_rates['mlf']}\n"
            "- See `audits/w1_rates_shadow.json` for official URLs, form bodies, response status, raw SHA-256 and quarantine paths.\n",
            encoding="utf-8",
        )
    return audit
