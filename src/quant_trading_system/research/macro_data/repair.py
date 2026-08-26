"""Auditable repairs for confirmed defects in legacy macro Bronze files."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .backfill import SHIBOR_SERIES_TO_TUSHARE


EXPECTED_SWAP_START = "2022-04-18"
EXPECTED_SWAP_END = "2022-05-17"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def detect_shibor_on_3m_swap(
    official_path: Path, bronze_path: Path
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Prove that every overlap mismatch is an exact O/N versus 3M swap."""
    official = pd.read_parquet(official_path)
    official = official[["series_id", "reference_period", "value"]].rename(
        columns={"value": "value_official"}
    )
    bronze = pd.read_parquet(bronze_path)
    melted = bronze.melt(
        "date",
        value_vars=list(SHIBOR_SERIES_TO_TUSHARE.values()),
        var_name="field",
        value_name="value_bronze",
    )
    melted["series_id"] = melted["field"].map(
        {field: series_id for series_id, field in SHIBOR_SERIES_TO_TUSHARE.items()}
    )
    melted["reference_period"] = pd.to_datetime(
        melted["date"], format="%Y%m%d"
    ).dt.strftime("%Y-%m-%d")
    joined = official.merge(
        melted[["series_id", "reference_period", "value_bronze"]],
        on=["series_id", "reference_period"],
        how="inner",
    )
    joined["absolute_difference"] = (
        joined["value_official"] - joined["value_bronze"]
    ).abs()
    mismatches = joined.loc[joined["absolute_difference"] > 1e-9].copy()
    swap_dates: list[str] = []
    for reference_period, group in mismatches.groupby("reference_period"):
        rows = {str(row.series_id): row for row in group.itertuples()}
        overnight = rows.get("CN.SHIBOR.ON")
        three_month = rows.get("CN.SHIBOR.3M")
        if (
            len(group) == 2
            and overnight is not None
            and three_month is not None
            and abs(overnight.value_official - three_month.value_bronze) <= 1e-9
            and abs(three_month.value_official - overnight.value_bronze) <= 1e-9
        ):
            swap_dates.append(str(reference_period))
    exact_swap_only = bool(swap_dates) and len(swap_dates) * 2 == len(mismatches)
    report = {
        "overlap_cells": int(len(joined)),
        "matching_cells": int(len(joined) - len(mismatches)),
        "mismatch_cells": int(len(mismatches)),
        "affected_dates": sorted(swap_dates),
        "affected_date_count": len(swap_dates),
        "affected_min": min(swap_dates) if swap_dates else None,
        "affected_max": max(swap_dates) if swap_dates else None,
        "exact_on_3m_swap_only": exact_swap_only,
    }
    return report, mismatches


def repair_shibor_bronze(
    *, official_path: Path, bronze_path: Path, shard_path: Path, repair_root: Path
) -> dict[str, Any]:
    """Repair a narrowly proven swap while preserving byte-identical originals."""
    for path in (official_path, bronze_path, shard_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    detection, _ = detect_shibor_on_3m_swap(official_path, bronze_path)
    if not (
        detection["exact_on_3m_swap_only"]
        and detection["affected_date_count"] == 21
        and detection["mismatch_cells"] == 42
        and detection["affected_min"] == EXPECTED_SWAP_START
        and detection["affected_max"] == EXPECTED_SWAP_END
    ):
        raise ValueError(f"Refusing repair: unexpected anomaly set: {detection}")

    original_dir = repair_root / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    before: dict[str, dict[str, Any]] = {}
    for label, path in (("aggregate", bronze_path), ("year_2022", shard_path)):
        digest = _sha256(path)
        backup = original_dir / f"{path.stem}.{digest}{path.suffix}"
        if not backup.exists():
            shutil.copy2(path, backup)
        if _sha256(backup) != digest:
            raise OSError(f"Backup verification failed: {backup}")
        before[label] = {
            "path": str(path.resolve()),
            "sha256": digest,
            "backup_path": str(backup.resolve()),
        }

    official = pd.read_parquet(official_path).pivot(
        index="reference_period", columns="series_id", values="value"
    )
    official.index = official.index.astype(str)
    official_columns = {
        field: series_id for series_id, field in SHIBOR_SERIES_TO_TUSHARE.items()
    }
    affected_dates = detection["affected_dates"]
    repaired_frames: dict[str, pd.DataFrame] = {}
    for label, path in (("aggregate", bronze_path), ("year_2022", shard_path)):
        frame = pd.read_parquet(path)
        date_text = pd.to_datetime(frame["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        mask = date_text.isin(affected_dates)
        if int(mask.sum()) != 21:
            raise ValueError(f"Refusing repair: {label} contains {int(mask.sum())} affected rows")
        for field, series_id in official_columns.items():
            frame.loc[mask, field] = date_text.loc[mask].map(official[series_id])
        repaired_frames[label] = frame

    candidate_aggregate = repaired_frames["aggregate"]
    candidate_2022 = candidate_aggregate.loc[
        pd.to_datetime(candidate_aggregate["date"], format="%Y%m%d").dt.year == 2022
    ].sort_values("date").reset_index(drop=True)
    candidate_shard = repaired_frames["year_2022"].sort_values("date").reset_index(drop=True)
    if not candidate_2022.equals(candidate_shard):
        raise ValueError(
            "Refusing repair: candidate aggregate and 2022 shard differ by key or value"
        )

    for label, path in (("aggregate", bronze_path), ("year_2022", shard_path)):
        _atomic_parquet(repaired_frames[label], path)

    after_detection, _ = detect_shibor_on_3m_swap(official_path, bronze_path)
    if after_detection["mismatch_cells"] != 0:
        raise OSError(f"Post-repair reconciliation failed: {after_detection}")
    aggregate = pd.read_parquet(bronze_path)
    shard = pd.read_parquet(shard_path).sort_values("date").reset_index(drop=True)
    aggregate_2022 = aggregate.loc[
        pd.to_datetime(aggregate["date"], format="%Y%m%d").dt.year == 2022
    ].sort_values("date").reset_index(drop=True)
    if not aggregate_2022.equals(shard):
        raise OSError("Post-repair aggregate and 2022 shard differ by key or value")

    result = {
        "repair_id": "R011_SHIBOR_ON_3M_SWAP_2022",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_source": "CFETS/Shibor public data",
        "official_path": str(official_path.resolve()),
        "official_sha256": _sha256(official_path),
        "precondition": detection,
        "before": before,
        "after": {
            "aggregate_sha256": _sha256(bronze_path),
            "year_2022_sha256": _sha256(shard_path),
            "reconciliation": after_detection,
            "aggregate_2022_equals_shard_by_date_key": True,
        },
        "recovery": "Restore the two backup files recorded under before to their original paths.",
    }
    repair_root.mkdir(parents=True, exist_ok=True)
    manifest = repair_root / "repair_manifest.json"
    temporary = manifest.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(manifest)
    result["manifest_path"] = str(manifest.resolve())
    return result
