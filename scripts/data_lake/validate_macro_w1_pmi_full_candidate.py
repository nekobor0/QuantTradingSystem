"""Independent real-archive validator for the PMI full-vintage candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_pmi_history import run_full_candidate  # noqa: E402


def _summary(audit: dict[str, Any]) -> str:
    source = audit["sources"][0]
    detail = source["history_detail"]
    return (
        "# PMI full-vintage candidate audit\n\n"
        f"- Window: {audit['requested_window']['start']}—{audit['requested_window']['end']}\n"
        f"- Direct projection: expected={len(audit['expected_periods'])}, observed={len(audit['observed_periods'])}, explained gaps={len(detail['explained_missing_cells'])}\n"
        f"- Full-vintage rows: {source['full_vintage_row_count']}; independent vintages: {source['full_vintage_count']}; parsed direct pages: {source['archive_entry_count']}; archive hashes: {detail['raw_hash']['checked']} checked, {len(detail['raw_hash']['failures'])} failed\n"
        f"- Layouts: {source['layout_counts']}\n"
        f"- Duplicate vintage keys: {audit['duplicate_primary_keys']}; value-domain failures: {audit['value_domain_failures']}\n"
        f"- Canonical v2: {source['canonical_validation']['passed']}; pit_grade=A; license_scope=internal_research\n"
        "- Curated write: not performed; this validator is audit-only.\n"
        "- research_ready: false\n\n"
        "## Series coverage\n\n"
        + "\n".join(
            f"- {series_id}: expected {item['expected_start']}—{item['expected_end']}; observed {item['observed_start']}—{item['observed_end']} ({item['observed_count']})"
            for series_id, item in source["series_coverage"].items()
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2009-06")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    result = run_full_candidate(args.output_root, args.start, args.end)
    frame = result.pop("_frame")
    audit = result["audit"]
    output = args.output_root / "audits" / "w1_pmi_state_full_candidate.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"audit": audit, "validation": result["validation"], "candidate": {"full_vintage_rows": len(frame), "curated_written": False, "research_ready": False}}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    summary = output.with_name("w1_pmi_state_full_candidate_summary.md")
    summary.write_text(_summary(audit), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": str(summary), "validation": result["validation"], "curated_written": False, "research_ready": False}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["validation"]["passed"] else 1)


if __name__ == "__main__":
    main()
