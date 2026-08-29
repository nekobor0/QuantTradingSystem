"""Offline importer for the frozen NBS official manual-export batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_nbs_manual_exports import run_manual_import  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=ROOT / "artifacts" / "macro_r011" / "raw" / "nbs_growth_output_official" / "enablement")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--pit-a-candidate", type=Path)
    args = parser.parse_args()
    result = run_manual_import(raw_root=args.raw_root, output_root=args.output_root, pit_a_candidate=args.pit_a_candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if not result["missing"] else 2)


if __name__ == "__main__":
    main()
