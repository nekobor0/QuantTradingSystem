"""Fetch, snapshot, normalize, validate, and gate macro observations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .adapters import parse_pmi_release, parse_shibor
from .contracts import (
    RawSnapshot,
    Registry,
    SeriesSpec,
    capture_raw_snapshot,
    load_registry,
    snapshot_as_dict,
    write_normalized_snapshot,
)


@dataclass(frozen=True, slots=True)
class HttpResult:
    payload: bytes
    status: int
    headers: Mapping[str, str]
    final_url: str


def fetch_public_url(url: str, *, method: str, timeout_seconds: int = 30, attempts: int = 3) -> HttpResult:
    request = Request(
        url,
        method=method.upper(),
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "User-Agent": "QuantTradingSystem-R011-internal-research/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return HttpResult(
                    payload=response.read(),
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    final_url=response.url,
                )
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def validate_canonical(frame: pd.DataFrame, specs: tuple[SeriesSpec, ...]) -> dict[str, object]:
    checks: dict[str, bool] = {}
    checks["non_empty"] = not frame.empty
    key = ["series_id", "reference_period", "vintage_id"]
    checks["unique_series_period_vintage"] = not frame.duplicated(key).any()
    checks["no_null_contract_fields"] = not frame[[
        "series_id", "reference_period", "value", "source_id", "release_at", "available_at",
        "tradable_at", "retrieved_at", "vintage_id", "raw_sha256",
    ]].isna().any().any()
    release = pd.to_datetime(frame["release_at"], utc=True, errors="coerce")
    available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    tradable = pd.to_datetime(frame["tradable_at"], utc=True, errors="coerce")
    retrieved = pd.to_datetime(frame["retrieved_at"], utc=True, errors="coerce")
    checks["timestamps_parse"] = not (
        release.isna().any() or available.isna().any() or tradable.isna().any() or retrieved.isna().any()
    )
    checks["available_not_before_release"] = bool((available >= release).all())
    checks["tradable_not_before_available"] = bool((tradable >= available).all())
    checks["retrieved_not_before_available"] = bool((retrieved >= available).all())
    by_id = {item.series_id: item for item in specs}
    checks["registered_series_only"] = set(frame["series_id"]).issubset(by_id)
    bounds_ok = True
    for series_id, group in frame.groupby("series_id"):
        spec = by_id.get(str(series_id))
        if spec is None or not group["value"].between(spec.value_min, spec.value_max).all():
            bounds_ok = False
    checks["values_within_registered_bounds"] = bounds_ok
    checks["raw_hash_shape"] = bool(frame["raw_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").all())
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {"passed": not failures, "checks": checks, "failures": failures, "rows": len(frame)}


def _run_sample(
    *,
    registry: Registry,
    source_id: str,
    output_root: Path,
    request_url: str,
    method: str,
    extension: str,
    parser: Callable[[bytes, RawSnapshot], pd.DataFrame],
) -> dict[str, object]:
    response = fetch_public_url(request_url, method=method)
    retrieved_at = datetime.now(timezone.utc)
    snapshot = capture_raw_snapshot(
        output_root=output_root,
        source_id=source_id,
        payload=response.payload,
        retrieved_at=retrieved_at,
        request_method=method,
        request_url=response.final_url,
        response_status=response.status,
        response_headers=response.headers,
        extension=extension,
    )
    frame = parser(response.payload, snapshot)
    specs = registry.series_for_source(source_id)
    validation = validate_canonical(frame, specs)
    normalized_path = output_root / "normalized" / source_id / f"{snapshot.sha256}.parquet"
    write_normalized_snapshot(frame, normalized_path)
    readiness = "VALIDATED_DECISIONS_CONFIRMED" if validation["passed"] else "QUARANTINED"
    manifest = {
        "schema_version": 2,
        "source_id": source_id,
        "readiness": readiness,
        "research_ready": False,
        "human_confirmation_required": False,
        "normalized_path": str(normalized_path.resolve()),
        "snapshot": snapshot_as_dict(snapshot),
        "validation": validation,
        "series_ids": sorted(frame["series_id"].unique().tolist()),
        "reference_period_min": str(frame["reference_period"].min()),
        "reference_period_max": str(frame["reference_period"].max()),
    }
    manifest_path = normalized_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def run_shibor_sample(
    *, registry_path: Path, output_root: Path, start_date: str, end_date: str
) -> dict[str, object]:
    registry = load_registry(registry_path)
    source_id = "cfets_shibor_public"
    source = registry.source(source_id)
    request_url = f"{source.url}?{urlencode({'lang': 'cn', 'startDate': start_date, 'endDate': end_date})}"
    specs = registry.series_for_source(source_id)
    return _run_sample(
        registry=registry,
        source_id=source_id,
        output_root=output_root,
        request_url=request_url,
        method=source.method,
        extension="json",
        parser=lambda payload, snapshot: parse_shibor(payload, snapshot, specs),
    )


def run_pmi_sample(*, registry_path: Path, output_root: Path, release_url: str | None = None) -> dict[str, object]:
    registry = load_registry(registry_path)
    source_id = "nbs_pmi_release_archive"
    source = registry.source(source_id)
    return _run_sample(
        registry=registry,
        source_id=source_id,
        output_root=output_root,
        request_url=release_url or source.url,
        method=source.method,
        extension="html",
        parser=parse_pmi_release,
    )
