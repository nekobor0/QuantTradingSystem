"""Registry, immutable raw snapshots, and canonical macro contracts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd


CANONICAL_COLUMNS = [
    "series_id",
    "reference_period",
    "value",
    "unit",
    "seasonal_adjustment",
    "source_id",
    "source_record_id",
    "release_at",
    "available_at",
    "availability_evidence",
    "retrieved_at",
    "vintage_id",
    "raw_sha256",
    "parser_version",
]

SENSITIVE_QUERY_KEYS = {"api_key", "apikey", "auth", "password", "secret", "token"}


@dataclass(frozen=True, slots=True)
class SourceSpec:
    source_id: str
    provider: str
    authority: str
    acquisition_mode: str
    method: str
    url: str
    public_landing_page: str
    publication_rule: str
    automation_status: str
    request_interval_seconds: int


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    series_id: str
    source_id: str
    source_field: str
    frequency: str
    unit: str
    seasonal_adjustment: str
    value_min: float
    value_max: float


@dataclass(frozen=True, slots=True)
class Registry:
    version: int
    timezone: str
    sources: tuple[SourceSpec, ...]
    series: tuple[SeriesSpec, ...]

    def source(self, source_id: str) -> SourceSpec:
        return next(item for item in self.sources if item.source_id == source_id)

    def series_for_source(self, source_id: str) -> tuple[SeriesSpec, ...]:
        return tuple(item for item in self.series if item.source_id == source_id)


@dataclass(frozen=True, slots=True)
class RawSnapshot:
    source_id: str
    retrieved_at: str
    sha256: str
    bytes: int
    raw_path: str
    manifest_path: str
    request_method: str
    request_url: str
    response_status: int
    content_type: str


def load_registry(path: Path) -> Registry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = tuple(SourceSpec(**item) for item in payload["sources"])
    series = tuple(SeriesSpec(**item) for item in payload["series"])
    source_ids = [item.source_id for item in sources]
    series_ids = [item.series_id for item in series]
    if len(source_ids) != len(set(source_ids)) or len(series_ids) != len(set(series_ids)):
        raise ValueError("registry IDs must be unique")
    unknown = {item.source_id for item in series} - set(source_ids)
    if unknown:
        raise ValueError(f"series reference unknown sources: {sorted(unknown)}")
    return Registry(int(payload["version"]), str(payload["timezone"]), sources, series)


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, "REDACTED" if key.lower() in SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".atomic-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def capture_raw_snapshot(
    *,
    output_root: Path,
    source_id: str,
    payload: bytes,
    retrieved_at: datetime,
    request_method: str,
    request_url: str,
    response_status: int,
    response_headers: Mapping[str, str],
    extension: str,
) -> RawSnapshot:
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    digest = hashlib.sha256(payload).hexdigest()
    retrieved_utc = retrieved_at.astimezone(timezone.utc)
    directory = output_root / "raw" / source_id / retrieved_utc.strftime("%Y/%m/%d")
    raw_path = directory / f"{digest}.{extension.lstrip('.')}"
    capture_id = retrieved_utc.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = directory / f"{capture_id}.manifest.json"
    if raw_path.exists() and raw_path.read_bytes() != payload:
        raise RuntimeError(f"immutable snapshot collision: {raw_path}")
    if not raw_path.exists():
        _atomic_write(raw_path, payload)
    allowed_headers = {
        key.lower(): value
        for key, value in response_headers.items()
        if key.lower() in {"content-type", "date", "etag", "last-modified"}
    }
    manifest = {
        "schema_version": 1,
        "source_id": source_id,
        "retrieved_at": retrieved_utc.isoformat(),
        "sha256": digest,
        "bytes": len(payload),
        "raw_path": str(raw_path.resolve()),
        "request": {"method": request_method.upper(), "url": _redact_url(request_url)},
        "response": {"status": response_status, "headers": allowed_headers},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise RuntimeError(f"immutable manifest conflict: {manifest_path}")
    else:
        _atomic_write(manifest_path, manifest_bytes)
    return RawSnapshot(
        source_id=source_id,
        retrieved_at=retrieved_utc.isoformat(),
        sha256=digest,
        bytes=len(payload),
        raw_path=str(raw_path.resolve()),
        manifest_path=str(manifest_path.resolve()),
        request_method=request_method.upper(),
        request_url=_redact_url(request_url),
        response_status=response_status,
        content_type=allowed_headers.get("content-type", ""),
    )


def write_normalized_snapshot(frame: pd.DataFrame, output: Path) -> None:
    missing = set(CANONICAL_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"canonical frame missing columns: {sorted(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    frame[CANONICAL_COLUMNS].to_parquet(temporary, index=False)
    temporary.replace(output)


def snapshot_as_dict(snapshot: RawSnapshot) -> dict[str, Any]:
    return asdict(snapshot)
