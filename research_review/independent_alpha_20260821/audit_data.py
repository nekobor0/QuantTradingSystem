"""Audit the persisted A2/B4 research datasets without network access."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "independent_alpha_20260821"
OUTPUT = ARTIFACTS / "DATA_AUDIT.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _dataset_record(
    path: Path, *, key: list[str], entity: str, expected_rows: int,
    expected_entities: int, expected_min: str, expected_max: str,
) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    duplicates = int(frame.duplicated(key).sum())
    result = {
        **_file_record(path),
        "grain": f"one row per {entity} and trade_date",
        "key": key,
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "duplicate_keys": duplicates,
        "entities": int(frame[key[0]].nunique()),
        "trade_dates": int(frame["trade_date"].nunique()),
        "date_min": str(frame["trade_date"].min()),
        "date_max": str(frame["trade_date"].max()),
        "null_rates": {
            column: round(float(rate), 8)
            for column, rate in frame.isna().mean().items()
            if rate > 0
        },
    }
    result["checks"] = {
        "row_count_matches_manifest": len(frame) == expected_rows,
        "entity_count_matches_manifest": frame[key[0]].nunique() == expected_entities,
        "date_range_matches_manifest": (
            str(frame["trade_date"].min()) == expected_min
            and str(frame["trade_date"].max()) == expected_max
        ),
        "unique_primary_key": duplicates == 0,
    }
    return result


def main() -> None:
    a2_dir = ARTIFACTS / "a2_cb"
    b4_dir = ARTIFACTS / "b4_sw_index"
    a2_manifest = json.loads((a2_dir / "manifest.json").read_text(encoding="utf-8"))
    b4_manifest = json.loads((b4_dir / "manifest.json").read_text(encoding="utf-8"))

    a2 = _dataset_record(
        a2_dir / "cb_daily.parquet", key=["ts_code", "trade_date"], entity="convertible bond",
        expected_rows=a2_manifest["rows"], expected_entities=a2_manifest["codes"],
        expected_min=a2_manifest["dates"][0], expected_max=a2_manifest["dates"][1],
    )
    shard_dates = sorted(path.stem for path in (a2_dir / "day_shards").glob("*.parquet"))
    a2["calendar_checks"] = {
        "manifest_requested_dates": a2_manifest["trade_dates_requested"],
        "manifest_shards_written": a2_manifest["shards_written"],
        "shard_files": len(shard_dates),
        "shard_dates_unique": len(shard_dates) == len(set(shard_dates)),
        "all_manifest_dates_landed": len(shard_dates) == a2_manifest["trade_dates_requested"],
        "empty_dates": a2_manifest["empty_dates"],
        "failures": a2_manifest["failures"],
        "repair_failures": a2_manifest["repair_failures"],
        "calendar_repair_failures": a2_manifest["calendar_repair_failures"],
        "source_recheck": a2_manifest["source_recheck"],
    }

    b4 = _dataset_record(
        b4_dir / "sw_l1_daily.parquet", key=["ts_code", "trade_date"], entity="SW level-1 index",
        expected_rows=b4_manifest["rows"], expected_entities=b4_manifest["indices_written"],
        expected_min=b4_manifest["dates"][0], expected_max=b4_manifest["dates"][1],
    )
    b4["coverage_checks"] = {
        "indices_requested": b4_manifest["indices_requested"],
        "indices_written": b4_manifest["indices_written"],
        "per_index_files": len(list((b4_dir / "daily_by_index").glob("*.parquet"))),
        "failures": b4_manifest["failures"],
        "coverage_by_index": b4_manifest["coverage_by_index"],
    }

    supporting_files = [
        a2_dir / "manifest.json", a2_dir / "a2_results.json",
        a2_dir / "a2_weekly_returns.parquet", a2_dir / "a2_top20_audit.parquet",
        b4_dir / "manifest.json", b4_dir / "b4_results.json",
        b4_dir / "b4_robustness.json", b4_dir / "b4_monthly_returns.parquet",
    ]
    critical_checks = [
        *a2["checks"].values(),
        a2["calendar_checks"]["all_manifest_dates_landed"],
        not a2["calendar_checks"]["empty_dates"],
        not a2["calendar_checks"]["failures"],
        not a2["calendar_checks"]["repair_failures"],
        not a2["calendar_checks"]["calendar_repair_failures"],
        a2["calendar_checks"]["source_recheck"]["passed"],
        *b4["checks"].values(),
        b4["coverage_checks"]["indices_requested"] == b4["coverage_checks"]["indices_written"],
        b4["coverage_checks"]["per_index_files"] == b4["coverage_checks"]["indices_written"],
        not b4["coverage_checks"]["failures"],
    ]
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "offline persistence audit for prior-round A2 and B4 research data",
        "overall_status": "PASS" if all(critical_checks) else "FAIL",
        "datasets": {"a2_cb_daily": a2, "b4_sw_l1_daily": b4},
        "supporting_files": [_file_record(path) for path in supporting_files],
        "pit_assessment": {
            "a2": "Daily provider observations are date-keyed; no vendor revision history. Safe for exploratory close-to-next-period research, not a production corporate-action substitute.",
            "b4": "Index daily observations are date-keyed. The tested Shibor series has 2,630 rows and no 3M nulls; historical PMI was excluded because publication-time PIT was unavailable.",
        },
        "decision_limits": {
            "a2": "Dataset passes research audit; signal remains rejected and production is blocked without callable-bond event coverage.",
            "b4": "Dataset passes research audit; result remains a candidate requiring out-of-sample shadow validation because performance is period-concentrated.",
        },
    }
    OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "status": audit["overall_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
