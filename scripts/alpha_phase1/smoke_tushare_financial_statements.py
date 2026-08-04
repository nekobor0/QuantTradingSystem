"""Probe narrow PIT financial-statement schemas without persisting credentials."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts

from fetch_tushare_research_data import load_token


FIELDS = {
    "fina_indicator": (
        "ts_code,ann_date,end_date,update_flag,roe,roe_waa,grossprofit_margin,"
        "netprofit_margin,ocf_to_or,ocf_to_profit,debt_to_assets,q_sales_yoy,q_profit_yoy"
    ),
    "income": (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,update_flag,"
        "total_revenue,revenue,oper_cost,n_income,n_income_attr_p"
    ),
    "balancesheet": (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,update_flag,"
        "total_assets,total_liab,total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int,"
        "st_borr,lt_borr,bond_payable,accounts_receiv,inventories"
    ),
    "cashflow": (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,update_flag,"
        "n_cashflow_act"
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ts-code", default="000001.SZ")
    args = parser.parse_args()
    pro = ts.pro_api(load_token(args.config))
    probes = {}
    for api_name, fields in FIELDS.items():
        try:
            frame = getattr(pro, api_name)(
                ts_code=args.ts_code,
                start_date="20230101",
                end_date="20251231",
                fields=fields,
            )
            probes[api_name] = {
                "status": "ok",
                "rows": int(len(frame)),
                "columns": list(frame.columns),
                "end_dates": sorted(frame.get("end_date", []).astype(str).unique().tolist())
                if "end_date" in frame
                else [],
            }
        except Exception as exc:
            probes[api_name] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ts_code": args.ts_code,
        "probes": probes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
