from __future__ import annotations

import json

from scripts.v6 import summarize_tushare_backfill_v6 as summary


def _write_audits(audit_dir) -> None:
    audit_dir.mkdir()
    for phase, filename in summary.REQUIRED_AUDITS.items():
        payload = {
            "phase": phase,
            "status": "PASS",
            "staging_only": True,
            "publication": "NOT_PUBLISHED_TO_PRODUCTION",
            "task_count": 2,
            "counts": {"valid": 2},
            "failures": [],
            "rows": 3,
            "bytes": 4,
            "request_set_hash": phase,
        }
        (audit_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_summary_is_fail_closed_for_missing_invalid_and_blocked_audits(tmp_path) -> None:
    audit_dir = tmp_path / "audits"
    _write_audits(audit_dir)
    assert summary.summarize(audit_dir)["status"] == "PASS"

    blocked_path = audit_dir / summary.REQUIRED_AUDITS["event"]
    blocked = json.loads(blocked_path.read_text(encoding="utf-8"))
    blocked.update(status="DATA_BLOCKED", counts={"valid": 1}, failures=[{"key": "x"}])
    blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
    result = summary.summarize(audit_dir)
    assert result["status"] == "DATA_BLOCKED_PARTIAL"
    assert result["data_blocked_phases"] == ["event"]
    assert result["publication"] == "PROHIBITED_WHILE_DATA_BLOCKED_OR_INCOMPLETE"

    blocked_path.unlink()
    result = summary.summarize(audit_dir)
    assert result["status"] == "INCOMPLETE"
    assert result["missing_audits"] == ["event"]
