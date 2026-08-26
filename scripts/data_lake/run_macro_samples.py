"""Run R011 Shibor/PMI samples, formal backfills, and reconciliation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_trading_system.research.macro_data import (
    reconcile_tushare,
    run_pmi_backfill,
    run_pmi_sample,
    run_shibor_backfill,
    run_shibor_sample,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/macro_sample_registry.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/macro_r011"))
    parser.add_argument("--mode", choices=("sample", "backfill", "reconcile", "all"), default="sample")
    parser.add_argument("--source", choices=("all", "shibor", "pmi"), default="all")
    parser.add_argument("--shibor-start", default="2006-10-08")
    parser.add_argument("--shibor-end")
    parser.add_argument("--pmi-release-url")
    parser.add_argument("--pmi-refresh-catalog", action="store_true")
    parser.add_argument("--tushare-macro-root", type=Path)
    args = parser.parse_args()
    results: dict[str, object] = {}
    if args.mode == "sample":
        if args.source in {"all", "shibor"}:
            results["shibor"] = run_shibor_sample(
                registry_path=args.registry,
                output_root=args.output_root,
                start_date=args.shibor_start,
                end_date=args.shibor_end or args.shibor_start,
            )
        if args.source in {"all", "pmi"}:
            results["pmi"] = run_pmi_sample(
                registry_path=args.registry,
                output_root=args.output_root,
                release_url=args.pmi_release_url,
            )
    if args.mode in {"backfill", "all"}:
        if args.source in {"all", "shibor"}:
            results["shibor"] = run_shibor_backfill(
                registry_path=args.registry,
                output_root=args.output_root,
                start_date=args.shibor_start,
                end_date=args.shibor_end,
            )
        if args.source in {"all", "pmi"}:
            results["pmi"] = run_pmi_backfill(
                registry_path=args.registry,
                output_root=args.output_root,
                refresh_catalog=args.pmi_refresh_catalog,
            )
    if args.mode in {"reconcile", "all"}:
        if args.tushare_macro_root is None:
            parser.error("--tushare-macro-root is required for reconciliation")
        results["reconciliation"] = reconcile_tushare(
            output_root=args.output_root,
            tushare_macro_root=args.tushare_macro_root,
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
