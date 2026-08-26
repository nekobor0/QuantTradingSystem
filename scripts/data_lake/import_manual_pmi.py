"""Import an NBS National Data PMI export, then rebuild the existing PMI audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_trading_system.research.macro_data.backfill import run_pmi_backfill
from quant_trading_system.research.macro_data.manual_import import import_manual_nbs_pmi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/macro_sample_registry.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/macro_r011"))
    parser.add_argument("--workbook", type=Path, required=True)
    args = parser.parse_args()
    imported = import_manual_nbs_pmi(
        registry_path=args.registry,
        output_root=args.output_root,
        workbook_path=args.workbook,
    )
    audit = run_pmi_backfill(registry_path=args.registry, output_root=args.output_root)
    print(json.dumps({"import": imported, "pmi_backfill": audit}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
