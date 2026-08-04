"""Append-only V6 live-shadow record store."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "strategy_id",
    "signal_time",
    "data_manifest_hash",
    "config_hash",
    "code_hash",
    "factor_exposures",
    "target_holdings",
    "actual_holdings",
    "unfilled_reasons",
    "simulated_open_prices",
    "slippage",
    "turnover",
    "fees",
    "industry_exposure",
    "style_exposure",
    "beta",
    "capacity",
    "shadow_nav",
    "benchmark_nav",
    "backtest_deviation",
}
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STRATEGY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
DATE_PATTERN = re.compile(r"^\d{8}$")
NUMERIC_FIELDS = {
    "factor_exposures",
    "target_holdings",
    "actual_holdings",
    "simulated_open_prices",
    "slippage",
    "turnover",
    "fees",
    "industry_exposure",
    "style_exposure",
    "beta",
    "capacity",
    "shadow_nav",
    "benchmark_nav",
    "backtest_deviation",
}


def _validate_finite(value: Any, field: str) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _validate_finite(nested, field)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _validate_finite(nested, field)
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must contain numeric values")
    elif not math.isfinite(float(value)):
        raise ValueError(f"{field} contains non-finite value")


def _write_exclusive_atomic(destination: Path, payload: dict[str, Any]) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise FileExistsError(
            f"live-shadow record already exists and cannot be overwritten: {destination}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_shadow_record(record: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS.difference(record)
    if missing:
        raise ValueError(f"missing live-shadow fields: {sorted(missing)}")
    signal_time = datetime.fromisoformat(str(record["signal_time"]))
    if signal_time.tzinfo is None:
        raise ValueError("signal_time must include timezone")
    for field in ("data_manifest_hash", "config_hash", "code_hash"):
        if not HASH_PATTERN.fullmatch(str(record[field])):
            raise ValueError(f"{field} must be a lowercase SHA256 hex digest")
    if not STRATEGY_PATTERN.fullmatch(str(record["strategy_id"])):
        raise ValueError("strategy_id contains unsafe characters")
    for field in NUMERIC_FIELDS:
        _validate_finite(record[field], field)
    for field in ("target_holdings", "actual_holdings"):
        weights = record[field]
        if not isinstance(weights, dict):
            raise ValueError(f"{field} must be a mapping")
        if any(float(weight) < -1e-12 for weight in weights.values()):
            raise ValueError(f"{field} contains negative long-only weight")
        if sum(float(weight) for weight in weights.values()) > 1.0 + 1e-10:
            raise ValueError(f"{field} exceeds total portfolio weight")


def append_shadow_record(root: Path, record: dict[str, Any]) -> Path:
    validate_shadow_record(record)
    signal_time = datetime.fromisoformat(str(record["signal_time"]))
    strategy = str(record["strategy_id"])
    destination = root / strategy / f"{signal_time:%Y%m%d}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload["record_hash"] = canonical_hash(record)
    _write_exclusive_atomic(destination, payload)
    return destination


def append_shadow_correction(
    root: Path,
    strategy_id: str,
    signal_date: str,
    correction_time: str,
    reason: str,
    changes: dict[str, Any],
) -> Path:
    if not STRATEGY_PATTERN.fullmatch(strategy_id):
        raise ValueError("strategy_id contains unsafe characters")
    if not DATE_PATTERN.fullmatch(signal_date):
        raise ValueError("signal_date must use YYYYMMDD")
    original = root / strategy_id / f"{signal_date}.json"
    if not original.exists():
        raise FileNotFoundError(original)
    original_payload = json.loads(original.read_text(encoding="utf-8"))
    timestamp = datetime.fromisoformat(correction_time)
    if timestamp.tzinfo is None:
        raise ValueError("correction_time must include timezone")
    payload = {
        "strategy_id": strategy_id,
        "signal_date": signal_date,
        "correction_time": correction_time,
        "reason": reason,
        "changes": changes,
        "original_record_hash": original_payload["record_hash"],
    }
    destination = (
        root
        / strategy_id
        / "corrections"
        / f"{signal_date}_{timestamp:%Y%m%dT%H%M%S%f}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_exclusive_atomic(destination, payload)
    return destination
