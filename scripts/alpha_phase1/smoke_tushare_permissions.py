"""Run small, non-secret Tushare permission and schema checks.

The script intentionally requests only narrow samples.  It never prints or
persists the token, and writes a JSON result suitable for the Phase 1 audit.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tushare as ts
import yaml


def _load_token(config_path: Path | None) -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        return token
    if config_path is None:
        raise RuntimeError("Set TUSHARE_TOKEN or provide --config")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    token = str(config.get("data", {}).get("token", "")).strip()
    if not token:
        raise RuntimeError("Tushare token is missing from the selected config")
    return token


def _probe(pro: Any, api_name: str, **params: str) -> dict[str, Any]:
    try:
        frame = getattr(pro, api_name)(**params)
        result = {
            "status": "ok",
            "rows": int(len(frame)),
            "columns": list(frame.columns),
        }
        for date_column in ("trade_date", "cal_date"):
            if date_column in frame.columns and not frame.empty:
                values = frame[date_column].dropna().astype(str)
                result[f"{date_column}_min"] = values.min()
                result[f"{date_column}_max"] = values.max()
                result[f"{date_column}_unique"] = int(values.nunique())
        return result
    except Exception as exc:  # Tushare exposes server errors as generic exceptions.
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    token = _load_token(args.config)
    pro = ts.pro_api(token)
    probes = {
        "stock_basic": _probe(
            pro,
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,delist_date",
        ),
        "trade_cal": _probe(
            pro,
            "trade_cal",
            exchange="SSE",
            start_date="20250801",
            end_date="20250831",
        ),
        "daily_basic": _probe(
            pro,
            "daily_basic",
            trade_date="20250813",
            fields=(
                "ts_code,trade_date,close,turnover_rate,turnover_rate_f,"
                "volume_ratio,total_share,float_share,free_share,total_mv,circ_mv"
            ),
        ),
        "adj_factor": _probe(
            pro,
            "adj_factor",
            ts_code="000001.SZ",
            start_date="20250801",
            end_date="20250813",
        ),
        "index_classify": _probe(
            pro,
            "index_classify",
            level="L1",
            src="SW2021",
        ),
        "index_member_all": _probe(
            pro,
            "index_member_all",
            ts_code="000001.SZ",
            is_new="N",
        ),
        "index_weight": _probe(
            pro,
            "index_weight",
            index_code="000300.SH",
            start_date="20250801",
            end_date="20250831",
        ),
        "stock_st": _probe(
            pro,
            "stock_st",
            trade_date="20250813",
        ),
        "stk_limit": _probe(
            pro,
            "stk_limit",
            trade_date="20250813",
        ),
        "suspend_d": _probe(
            pro,
            "suspend_d",
            trade_date="20250813",
        ),
        "moneyflow": _probe(
            pro,
            "moneyflow",
            trade_date="20250813",
        ),
        "stk_holdernumber": _probe(
            pro,
            "stk_holdernumber",
            ts_code="000001.SZ",
            start_date="20240101",
            end_date="20251231",
        ),
        "pledge_stat": _probe(
            pro,
            "pledge_stat",
            ts_code="000001.SZ",
        ),
        "pledge_detail": _probe(
            pro,
            "pledge_detail",
            ts_code="000001.SZ",
        ),
        "fina_indicator": _probe(
            pro,
            "fina_indicator",
            ts_code="000001.SZ",
            start_date="20240101",
            end_date="20251231",
            fields=(
                "ts_code,ann_date,end_date,roe,roe_waa,grossprofit_margin,"
                "netprofit_margin,ocf_to_or,ocf_to_profit,debt_to_assets,"
                "q_sales_yoy,q_profit_yoy"
            ),
        ),
    }
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tushare_version": ts.__version__,
        "probe_count": len(probes),
        "probes": probes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
