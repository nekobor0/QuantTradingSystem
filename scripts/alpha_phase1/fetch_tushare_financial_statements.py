"""Fetch quarterly PIT financial data by stock with resumable immutable shards."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fetch_tushare_research_data import (
    combine_shards,
    file_summary,
    load_token,
    make_task,
    run_tasks,
)


DATASETS = {
    "fina_indicator": {
        "fields": (
            "ts_code,ann_date,end_date,update_flag,roe,roe_waa,grossprofit_margin,"
            "netprofit_margin,ocf_to_or,ocf_to_profit,debt_to_assets,q_sales_yoy,q_profit_yoy"
        ),
        "required": ("ts_code", "ann_date", "end_date"),
    },
    "income": {
        "fields": (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,update_flag,"
            "total_revenue,revenue,oper_cost,n_income,n_income_attr_p"
        ),
        "required": ("ts_code", "ann_date", "end_date"),
    },
    "balancesheet": {
        "fields": (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,update_flag,"
            "total_assets,total_liab,total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int,"
            "st_borr,lt_borr,bond_payable,accounts_receiv,inventories"
        ),
        "required": ("ts_code", "ann_date", "end_date"),
    },
    "cashflow": {
        "fields": (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,update_flag,"
            "n_cashflow_act"
        ),
        "required": ("ts_code", "ann_date", "end_date"),
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--stock-basic", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--datasets", nargs="+", choices=sorted(DATASETS), default=["fina_indicator"])
    parser.add_argument("--start-date", default="20160101")
    parser.add_argument("--end-date", default="20260730")
    parser.add_argument("--calls-per-minute", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.calls_per_minute <= 200:
        raise ValueError("calls-per-minute must be in [1, 200] for the 3000-point tier")

    stocks = pd.read_parquet(args.stock_basic, columns=["ts_code"])["ts_code"].dropna().astype(str)
    symbols = sorted(stocks.unique())
    tasks = []
    for dataset in args.datasets:
        spec = DATASETS[dataset]
        for symbol in symbols:
            tasks.append(
                make_task(
                    dataset,
                    symbol.replace(".", "_"),
                    dataset,
                    {
                        "ts_code": symbol,
                        "start_date": args.start_date,
                        "end_date": args.end_date,
                        "fields": str(spec["fields"]),
                    },
                    spec["required"],
                    allow_empty=True,
                )
            )
    results = run_tasks(
        tasks,
        args.output_dir,
        load_token(args.config),
        args.calls_per_minute,
        args.workers,
        args.max_attempts,
    )
    errors = [result for result in results if result["status"] == "error"]
    files = {}
    if not errors:
        for dataset in args.datasets:
            files[dataset] = file_summary(combine_shards(args.output_dir, dataset))
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": len(symbols),
        "datasets": args.datasets,
        "requests": len(tasks),
        "status_counts": pd.Series([result["status"] for result in results]).value_counts().to_dict(),
        "errors": errors,
        "files": files,
        "rate_limit": args.calls_per_minute,
        "date_range": [args.start_date, args.end_date],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.output_dir / "financial_statements_manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(f"financial fetch stopped with {len(errors)} errors; inspect {manifest}")


if __name__ == "__main__":
    main()
