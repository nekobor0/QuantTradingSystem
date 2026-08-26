"""Repair the confirmed R011 legacy Shibor O/N versus 3M swap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_trading_system.research.macro_data.repair import repair_shibor_bronze


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--bronze", type=Path, required=True)
    parser.add_argument("--shard-2022", type=Path, required=True)
    parser.add_argument("--repair-root", type=Path, required=True)
    args = parser.parse_args()
    result = repair_shibor_bronze(
        official_path=args.official.resolve(),
        bronze_path=args.bronze.resolve(),
        shard_path=args.shard_2022.resolve(),
        repair_root=args.repair_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
