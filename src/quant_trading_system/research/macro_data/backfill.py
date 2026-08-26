"""Resumable official-source backfills and independent Tushare reconciliation."""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .contracts import CANONICAL_COLUMNS, load_registry, write_normalized_snapshot
from .pipeline import run_pmi_sample, run_shibor_sample, validate_canonical


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


def _combine_normalized(output_root: Path, source_id: str, destination: Path) -> pd.DataFrame:
    paths = sorted((output_root / "normalized" / source_id).glob("*.parquet"))
    if not paths:
        raise ValueError(f"no normalized shards for {source_id}")
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
    frame = _combine_normalized(output_root, "nbs_pmi_release_archive", destination)
    validation = validate_canonical(frame, registry.series_for_source("nbs_pmi_release_archive"))
    parsed_periods = set(frame["reference_period"].astype(str))
    start = min(parsed_periods)
    end = max(parsed_periods)
    expected = set(pd.period_range(start, end, freq="M").astype(str))
    report = {
        "source_id": "nbs_pmi_release_archive",
        "catalog_pages": len(catalog),
        "completed_pages": len(completed),
        "failures": state["failures"],
        "rows": len(frame),
        "vintages": int(frame["vintage_id"].nunique()),
        "reference_period_min": start,
        "reference_period_max": end,
        "missing_reference_periods_within_parsed_range": sorted(expected - parsed_periods),
        "validation": validation,
        "research_ready": not state["failures"] and validation["passed"] and not (expected - parsed_periods),
        "restriction": "known monthly coverage gap must be excluded explicitly" if expected - parsed_periods else None,
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
            "shibor_restriction": "historical capture timing and quarantined Tushare O/N-3M swap",
        },
    }
    _write_json(output_root / "audits" / "tushare_reconciliation.json", report)
    return report
