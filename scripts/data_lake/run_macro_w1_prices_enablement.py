"""Acquire and audit official NBS CPI/PPI shadow data without curated writes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_prices_history import run_history_shadow  # noqa: E402


def _summary(result: dict[str, object]) -> str:
    audit = result["audit"]
    source = audit["sources"][0]
    return "\n".join(
        [
            "# W1 prices official shadow summary",
            "",
            f"- Window: {audit['requested_window']['start']}—{audit['requested_window']['end']}",
            f"- History scope: PIT-A release window {source['history_scope']['pit_a_window']['start']}—{source['history_scope']['pit_a_window']['end']}; pre-2021={source['history_scope']['pre_2021_status']}; long-history target is not claimed.",
            f"- Expected periods: {len(audit['expected_periods'])}; observed periods: {len(audit['observed_periods'])}",
            f"- Listing periods: {source['official_listing']['coverage_count']}",
            f"- Search/replay candidate periods: " + ", ".join(f"{item['term']}={item['candidate_count']}" for item in source["official_search_replay"]),
            f"- Downloaded CPI/PPI/interpretation pages: {source['actual_download']['cpi_pages']}/{source['actual_download']['ppi_pages']}/{source['actual_download']['interpretation_pages']}",
            f"- Parsed rows: {source['successful_parse']['rows']}; missing cells: {len(source['expected_period_coverage']['missing_cells'])}; unexplained: {len(audit['unexplained_missing'])}",
            f"- Raw hashes: {source['raw_hash']['checked']} checked; {len(source['raw_hash']['failures'])} failures; duplicate keys: {audit['duplicate_primary_keys']}",
            f"- Methodology evidence: {len(source['methodology_evidence'])} regime(s); PIT={source['pit_grade']}; license={source['license_scope']}",
            f"- research_ready: {audit['research_ready']}; curated write: false",
            "",
            "Coverage is reported separately for official listing, official search/replay, actual downloads, successful parses, and expected periods.",
        ]
    ) + "\n"


def run_shadow(output_root: Path, start: str, end: str) -> dict[str, object]:
    result = run_history_shadow(output_root, start, end, full=False)
    frame = result.pop("_frame")
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        output = output_root / "normalized" / "w1_prices_bounded_shadow.parquet"
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output, index=False)
    audit_path = output_root / "audits" / "w1_prices_shadow.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary_path = output_root / "audits" / "w1_prices_shadow_summary.md"
    summary_path.write_text(_summary(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("shadow", "full"), default="shadow")
    parser.add_argument("--start", default="2024-08")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    if args.mode == "full":
        print(json.dumps({"blocked": True, "blockers": [{"code": "FULL_HISTORY_NOT_ALLOWED", "detail": "execution manifest gate"}], "research_ready": False}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    result = run_shadow(args.output_root, args.start, args.end)
    print(json.dumps({"audit": result["audit"], "validation": result["validation"]}, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["validation"]["passed"] and not result["audit"]["blocked"] else 1)


if __name__ == "__main__":
    main()
