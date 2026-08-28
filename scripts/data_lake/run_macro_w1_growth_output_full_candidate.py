"""Run the audit-only full-history growth-output candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_growth_full_history import run_full_candidate, write_source_map  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--source-map-only", action="store_true")
    parser.add_argument("--fetch-probes", action="store_true", help="fetch only source-map probes; existing release raw is always reused")
    args = parser.parse_args()
    if args.source_map_only:
        print(json.dumps({"source_map": str(write_source_map(args.output_root).resolve()), "research_ready": False}, ensure_ascii=False, indent=2))
        return
    result = run_full_candidate(args.output_root, fetch_probes=args.fetch_probes)
    print(json.dumps({
        "output": str(args.output_root / "audits" / "w1_growth_output_full_range_audit.json"),
        "candidate": result["candidate"],
        "blocked": result["blocked"],
        "validation": result["validation"],
        "research_ready": False,
    }, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if not result["blocked"] else 2)


if __name__ == "__main__":
    main()
