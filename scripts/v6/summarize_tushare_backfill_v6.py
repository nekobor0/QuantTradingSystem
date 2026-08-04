"""Consolidate phase audits into one fail-closed Tushare V6 acceptance record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.v6.backfill_tushare_v6 import write_json_atomic


REQUIRED_AUDITS = {
    "stock_basic_trade_cal": "tushare_backfill_seed_v6.json",
    "daily_1990_2004": "tushare_backfill_daily_1990_2004_v6.json",
    "adj_factor": "tushare_backfill_adj_factor_v6.json",
    "daily_basic": "tushare_backfill_daily_basic_v6.json",
    "moneyflow": "tushare_backfill_moneyflow_v6.json",
    "margin_detail": "tushare_backfill_margin_detail_v6.json",
    "stk_limit": "tushare_backfill_stk_limit_v6.json",
    "stock_st": "tushare_backfill_stock_st_v6.json",
    "financial": "tushare_backfill_financial_v6.json",
    "index": "tushare_backfill_index_v6.json",
    "event": "tushare_backfill_event_v6.json",
}


def summarize(audit_dir: Path) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    missing: list[str] = []
    invalid: list[str] = []
    for phase, filename in REQUIRED_AUDITS.items():
        path = audit_dir / filename
        if not path.exists():
            missing.append(phase)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        counts = payload.get("counts", {})
        valid = int(counts.get("valid", 0))
        task_count = int(payload.get("task_count", 0))
        status = payload.get("status")
        contract_ok = (
            payload.get("phase") == phase
            and payload.get("staging_only") is True
            and payload.get("publication") == "NOT_PUBLISHED_TO_PRODUCTION"
            and status in {"PASS", "DATA_BLOCKED"}
            and ((status == "PASS" and valid == task_count) or (status == "DATA_BLOCKED" and valid < task_count and bool(payload.get("failures"))))
        )
        if not contract_ok:
            invalid.append(phase)
        phases.append(
            {
                "phase": phase,
                "status": status,
                "task_count": task_count,
                "valid": valid,
                "missing_or_invalid": task_count - valid,
                "rows": int(payload.get("rows", 0)),
                "bytes": int(payload.get("bytes", 0)),
                "request_set_hash": payload.get("request_set_hash"),
                "audit": path.as_posix(),
            }
        )
    blocked = [item["phase"] for item in phases if item["status"] == "DATA_BLOCKED"]
    if missing or invalid:
        status = "INCOMPLETE"
    elif blocked:
        status = "DATA_BLOCKED_PARTIAL"
    else:
        status = "PASS"
    return {
        "version": 6,
        "status": status,
        "required_phase_count": len(REQUIRED_AUDITS),
        "audited_phase_count": len(phases),
        "missing_audits": missing,
        "invalid_audits": invalid,
        "data_blocked_phases": blocked,
        "total_rows": sum(item["rows"] for item in phases),
        "total_bytes": sum(item["bytes"] for item in phases),
        "phases": phases,
        "publication": "NOT_PUBLISHED_TO_PRODUCTION" if status == "PASS" else "PROHIBITED_WHILE_DATA_BLOCKED_OR_INCOMPLETE",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Tushare V6 staging acceptance",
        "",
        f"- Status: `{payload['status']}`",
        f"- Audited phases: {payload['audited_phase_count']}/{payload['required_phase_count']}",
        f"- Rows: {payload['total_rows']:,}",
        f"- Publication: `{payload['publication']}`",
        "",
        "| Phase | Status | Valid / Tasks | Rows |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item['phase']} | {item['status']} | {item['valid']:,}/{item['task_count']:,} | {item['rows']:,} |"
        for item in payload["phases"]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, default=Path("artifacts/data_audits"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/data_audits/tushare_backfill_v6_acceptance.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("artifacts/data_audits/tushare_backfill_v6_acceptance.md"))
    args = parser.parse_args()
    payload = summarize(args.audit_dir)
    write_json_atomic(payload, args.output)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(f"Tushare V6 acceptance is {payload['status']}")


if __name__ == "__main__":
    main()
