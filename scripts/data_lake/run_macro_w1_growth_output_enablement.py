"""Run the bounded official NBS growth-output candidate (audit-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_growth_history import run_bounded_candidate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit-only", "shadow"), default="audit-only")
    parser.add_argument("--start", default="2024-08")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--discovery", choices=("combined", "index", "direct-search"), default="combined")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    result = run_bounded_candidate(args.output_root, args.start, args.end, discovery=args.discovery)
    audit = result["audit"]
    print(json.dumps({
        "output": str(args.output_root / "audits" / "w1_growth_output_bounded_candidate.json"),
        "candidate": result["candidate"],
        "expected": len(audit["expected_periods"]),
        "observed": len(audit["observed_periods"]),
        "blocked": audit["blocked"],
        "blockers": audit["blockers"],
        "validation": result["validation"],
        "research_ready": False,
    }, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["validation"]["passed"] and not audit["blocked"] else 1)


if __name__ == "__main__":
    main()
