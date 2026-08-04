"""Fail-closed audit for one identified Tushare V6 backfill phase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.v6 import backfill_tushare_v6 as backfill


def audit_phase(
    phase: str,
    project_root: Path,
    output_dir: Path,
    source_dir: Path,
    end_date: str,
) -> dict[str, object]:
    tasks = backfill.build_tasks(phase, source_dir, output_dir, end_date)
    results = []
    rows = 0
    total_bytes = 0
    date_min: str | None = None
    date_max: str | None = None
    date_bounds: dict[str, dict[str, str | None]] = {}
    for task in tasks:
        identity = {
            "dataset": task.dataset,
            "key": task.key,
            "api_name": task.api_name,
            "request_hash": backfill.request_hash(task),
        }
        path = output_dir / "shards" / task.dataset / f"{task.key}.parquet"
        if not path.exists():
            results.append({**identity, "status": "missing"})
            continue
        try:
            metadata = backfill._validate_cached(path, task)
        except Exception as error:
            results.append(
                {
                    **identity,
                    "status": "invalid",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
            continue
        rows += int(metadata["rows"])
        total_bytes += path.stat().st_size
        for field, bounds in metadata.get("date_bounds", {}).items():
            aggregate = date_bounds.setdefault(field, {"min": None, "max": None})
            lower, upper = bounds.get("min"), bounds.get("max")
            aggregate["min"] = lower if lower and (aggregate["min"] is None or lower < aggregate["min"]) else aggregate["min"]
            aggregate["max"] = upper if upper and (aggregate["max"] is None or upper > aggregate["max"]) else aggregate["max"]
        bounds = metadata.get("date_bounds", {}).get("trade_date", {})
        lower, upper = bounds.get("min"), bounds.get("max")
        date_min = lower if lower and (date_min is None or lower < date_min) else date_min
        date_max = upper if upper and (date_max is None or upper > date_max) else date_max
        results.append({**identity, "status": "valid"})
    counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "version": 6,
        "phase": phase,
        "status": "PASS" if counts.get("valid", 0) == len(tasks) else "DATA_BLOCKED",
        "staging_only": True,
        "output_dir": output_dir.as_posix(),
        "task_count": len(tasks),
        "counts": counts,
        "rows": rows,
        "bytes": total_bytes,
        "trade_date_min": date_min,
        "trade_date_max": date_max,
        "date_bounds": date_bounds,
        "failures": [result for result in results if result["status"] != "valid"],
        "request_set_hash": backfill._hash_payload(
            [backfill.request_hash(task) for task in tasks]
        ),
        "publication": "NOT_PUBLISHED_TO_PRODUCTION",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/data_backfill_v6/v2")
    )
    parser.add_argument(
        "--source-tushare-dir",
        type=Path,
        default=Path("artifacts/alpha_phase1/tushare"),
    )
    parser.add_argument("--end-date", type=backfill.validate_end_date, default="20260731")
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("artifacts/data_audits/tushare_backfill_phase_v6.json"),
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    output_dir = backfill.assert_staging_root(args.output_dir, project_root)
    source_dir = (
        args.source_tushare_dir
        if args.source_tushare_dir.is_absolute()
        else project_root / args.source_tushare_dir
    )
    payload = audit_phase(
        args.phase, project_root, output_dir, source_dir, args.end_date
    )
    backfill.write_json_atomic(payload, args.audit_output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit("backfill phase audit is DATA_BLOCKED")


if __name__ == "__main__":
    main()
