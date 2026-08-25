"""Run the R011 Shibor and PMI confirmation-gate samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_trading_system.research.macro_data import run_pmi_sample, run_shibor_sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/macro_sample_registry.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/macro_r011_samples"))
    parser.add_argument("--source", choices=("all", "shibor", "pmi"), default="all")
    parser.add_argument("--shibor-start", default="2026-08-18")
    parser.add_argument("--shibor-end", default="2026-08-25")
    parser.add_argument("--pmi-release-url")
    args = parser.parse_args()
    results: dict[str, object] = {}
    if args.source in {"all", "shibor"}:
        results["shibor"] = run_shibor_sample(
            registry_path=args.registry,
            output_root=args.output_root,
            start_date=args.shibor_start,
            end_date=args.shibor_end,
        )
    if args.source in {"all", "pmi"}:
        results["pmi"] = run_pmi_sample(
            registry_path=args.registry,
            output_root=args.output_root,
            release_url=args.pmi_release_url,
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
