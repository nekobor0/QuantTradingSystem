"""Build an audit-only official NBS prices full-range candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_prices_history import run_full_candidate  # noqa: E402


def _summary(result: dict[str, object]) -> str:
    audit = result["audit"]
    source = audit["sources"][0]
    return "\n".join(
        [
            "# W1 prices full candidate audit summary",
            "",
            "This is an audit-only candidate. The execution manifest remains full_history_allowed=false and no curated file is written.",
            "",
            f"- Window: {audit['requested_window']['start']}—{audit['requested_window']['end']}",
            f"- History scope: PIT-A release window {source['history_scope']['pit_a_window']['start']}—{source['history_scope']['pit_a_window']['end']}; pre-2021={source['history_scope']['pre_2021_status']}; long-history target is not claimed.",
            f"- Official listing periods: {source['official_listing']['coverage_count']}",
            f"- Search/replay candidate periods: " + ", ".join(f"{item['term']}={item['candidate_count']}" for item in source["official_search_replay"]),
            f"- Actual downloads: CPI={source['actual_download']['cpi_pages']}, PPI={source['actual_download']['ppi_pages']}, interpretation={source['actual_download']['interpretation_pages']}",
            f"- Successful parse: {len(audit['observed_periods'])}/{len(audit['expected_periods'])} periods; rows={source['successful_parse']['rows']}",
            f"- Missing classifications: official-page={len(source['official_page_missing'])}, fetch={len(source['fetch_failures'])}, parse={len(source['parse_failures'])}, unexplained={len(audit['unexplained_missing'])}",
            f"- Raw hash: {source['raw_hash']['checked']} checked; failures={len(source['raw_hash']['failures'])}",
            f"- Duplicate keys: {audit['duplicate_primary_keys']}; value-domain failures: {audit['value_domain_failures']}; canonical v2: {source['canonical_v2']['passed']}",
            f"- Methodology regimes: {[(item['regime'], item['base_year'], item['effective_period_start']) for item in source['methodology_evidence']]}",
            f"- PIT={source['pit_grade']}; license={source['license_scope']}; research_ready={audit['research_ready']}",
            "",
            "Listing, search/replay, actual download, successful parse, and expected-period coverage are intentionally reported separately.",
        ]
    ) + "\n"


def run(output_root: Path, start: str, end: str) -> dict[str, object]:
    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    package = next(item for item in manifest["packages"] if item["package_id"] == "prices")
    result = run_full_candidate(output_root, start, end)
    frame = result.pop("_frame", None)
    if frame is not None and not getattr(frame, "empty", True):
        result["candidate_rows"] = len(frame)
    result["curated_written"] = False
    result["research_ready"] = False
    result["gate"] = {"full_history_allowed": bool(package["full_history_allowed"]), "manifest_full_blockers": list(package["full_blockers"])}
    audit_path = output_root / "audits" / "w1_prices_full_candidate.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary_path = output_root / "audits" / "w1_prices_full_candidate_summary.md"
    summary_path.write_text(_summary(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-01")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    result = run(args.output_root, args.start, args.end)
    audit = result["audit"]
    print(json.dumps({"output": str(args.output_root / "audits" / "w1_prices_full_candidate.json"), "validation": result["validation"], "periods": [len(audit["expected_periods"]), len(audit["observed_periods"])], "rows": result.get("candidate_rows", 0), "blocked": audit["blocked"], "research_ready": False, "curated_written": False}, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["validation"]["passed"] else 1)


if __name__ == "__main__":
    main()
