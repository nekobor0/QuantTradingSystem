"""CLI and artifact writer for the bounded official NBS PMI shadow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import write_canonical_v2_snapshot  # noqa: E402
from quant_trading_system.research.macro_data.w1_pmi_history import (  # noqa: E402
    PmiParseResult,
    SERIES,
    _pseudo,
    _release_url,
    expected_cells,
    expected_by_series,
    expected_series_periods,
    parse_release,
    run_history_shadow,
)

# Backward-compatible test/import names; implementation lives in w1_pmi_history.
def parse_pmi_state_release(payload: bytes, reference_period: str) -> PmiParseResult:
    parsed = parse_release(payload, reference_period)
    if parsed.layout != "legacy_horizontal":
        return parsed
    present = {str(row["series_id"]) for row in parsed.rows}
    omissions = list(parsed.structural_omissions)
    omissions.extend(
        {"series_id": series_id, "reference_period": reference_period, "reason": "SERIES_NOT_PUBLISHED_IN_LAYOUT"}
        for series_id in SERIES
        if series_id not in present and not any(item["series_id"] == series_id for item in omissions)
    )
    return PmiParseResult(parsed.rows, tuple(omissions), parsed.publication_at, parsed.layout)


def _summary(audit: dict[str, object]) -> str:
    source = audit["sources"][0]  # type: ignore[index]
    detail = source["history_detail"]  # type: ignore[index]
    return (
        "# PMI state full-range shadow summary\n\n"
        "This is a bounded shadow audit using existing official NBS raw pages. "
        "No full-history package run or gate change was performed.\n\n"
        f"- Window: {audit['requested_window']['start']}—{audit['requested_window']['end']}\n"
        f"- Expected cells: {len(audit['expected_periods'])}; observed cells: {len(audit['observed_periods'])}\n"
        f"- Direct release periods: {detail['direct_release_page_coverage']}\n"
        f"- Explained missing cells: {len(detail['explained_missing_cells'])}; unexplained: {len(audit['unexplained_missing'])}\n"
        f"- Archive pages hashed: {detail['raw_hash']['checked']}; hash failures: {len(detail['raw_hash']['failures'])}; duplicate keys: {audit['duplicate_primary_keys']}\n"
        f"- Layouts: {detail['layout_counts']}\n"
        f"- PIT metadata: pit_grade={detail['pit_grade']}; license_scope={detail['license_scope']}\n"
        f"- research_ready: {audit['research_ready']}\n\n"
        "## Discovery mechanisms\n\n"
        "The current 67-page NBS listing and the existing official NBS search semantics are reported separately; the union is used only as discovery evidence. Historical values come from immutable official release raw/manifest pairs.\n\n"
        "## Missing direct release pages\n\n"
        + "\n".join(f"- `{item}`" for item in detail["official_release_page_not_discovered"])
        + "\n"
    )


def run_shadow(output_root: Path, start: str = "2009-06", end: str = "2026-07", *, refresh_listing: bool = False) -> dict[str, object]:
    result = run_history_shadow(output_root, start, end, refresh_listing=refresh_listing)
    frame = result.pop("_frame")
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        write_canonical_v2_snapshot(frame, output_root / "normalized" / "pmi_state_full_range_shadow.parquet")
    audit = result["audit"]
    audit_path = output_root / "audits" / "w1_pmi_state_full_range_shadow.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = output_root / "audits" / "w1_pmi_state_full_range_shadow_summary.md"
    summary_path.write_text(_summary(audit), encoding="utf-8")  # type: ignore[arg-type]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("shadow", "full"), default="shadow")
    parser.add_argument("--start", default="2009-06")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--refresh-listing", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    if args.mode == "full":
        result = {"blocked": True, "blockers": [{"code": "FULL_HISTORY_NOT_ALLOWED", "detail": "execution manifest gate"}], "research_ready": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    result = run_shadow(args.output_root, args.start, args.end, refresh_listing=args.refresh_listing)
    print(json.dumps({"audit": result["audit"], "validation": result["validation"]}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["validation"]["passed"] else 1)  # type: ignore[index]


if __name__ == "__main__":
    main()
