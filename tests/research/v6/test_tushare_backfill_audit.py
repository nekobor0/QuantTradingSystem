from __future__ import annotations

from scripts.v6 import audit_tushare_backfill_phase_v6 as audit
from scripts.v6 import backfill_tushare_v6 as backfill


def test_audit_failures_keep_full_task_identity_and_all_date_bounds(tmp_path, monkeypatch) -> None:
    tasks = [
        backfill.BackfillTask("dataset_a", "same_key", "api", {"code": "A"}, ("value",)),
        backfill.BackfillTask("dataset_b", "same_key", "api", {"code": "B"}, ("value",)),
    ]
    output_dir = tmp_path / "artifacts" / "data_backfill_v6" / "v2"
    first_path = output_dir / "shards" / "dataset_a" / "same_key.parquet"
    first_path.parent.mkdir(parents=True)
    first_path.write_bytes(b"shard")

    monkeypatch.setattr(backfill, "build_tasks", lambda *args: tasks)
    monkeypatch.setattr(
        backfill,
        "_validate_cached",
        lambda path, task: {
            "rows": 3,
            "date_bounds": {
                "ann_date": {"min": "20000101", "max": "20010101"},
                "end_date": {"min": "19991231", "max": "20001231"},
            },
        },
    )

    result = audit.audit_phase("event", tmp_path, output_dir, tmp_path, "20260731")

    assert result["status"] == "DATA_BLOCKED"
    assert result["date_bounds"] == {
        "ann_date": {"min": "20000101", "max": "20010101"},
        "end_date": {"min": "19991231", "max": "20001231"},
    }
    assert result["failures"] == [
        {
            "dataset": "dataset_b",
            "key": "same_key",
            "api_name": "api",
            "request_hash": backfill.request_hash(tasks[1]),
            "status": "missing",
        }
    ]
