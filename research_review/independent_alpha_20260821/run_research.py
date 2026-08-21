"""Availability probes and offline research for A2/B2/B3/B4.

This module never submits orders.  Network access is limited to read-only
Tushare research endpoints, using the token stored in ``~/.tushare_token``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "independent_alpha_20260821"


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "non_null": {column: int(frame[column].notna().sum()) for column in frame.columns},
    }


def probe() -> None:
    token = Path.home().joinpath(".tushare_token").read_text(encoding="utf-8").strip()
    pro = ts.pro_api(token)
    result: dict[str, Any] = {}

    fields = (
        "ts_code,trade_date,close,vol,amount,bond_value,bond_over_rate,"
        "cb_value,cb_over_rate"
    )
    for trade_date in ("20190719", "20240119", "20260820"):
        try:
            frame = pro.cb_daily(trade_date=trade_date, fields=fields)
            item = _summary(frame)
            item["ranges"] = {
                column: [float(frame[column].min()), float(frame[column].max())]
                for column in ("bond_value", "bond_over_rate", "cb_value", "cb_over_rate")
                if column in frame and frame[column].notna().any()
            }
            result[f"cb_daily_{trade_date}"] = item
        except Exception as exc:  # research probe records provider failures verbatim
            result[f"cb_daily_{trade_date}"] = {"error": str(exc)}

    try:
        latest = pro.cb_daily(trade_date="20260820")
        current_code = str(latest.iloc[0]["ts_code"])
        result["current_cb_code"] = current_code
        for endpoint in ("cb_basic", "cb_call", "cb_rating"):
            try:
                frame = getattr(pro, endpoint)(ts_code=current_code)
                result[endpoint] = _summary(frame)
                result[endpoint]["sample"] = frame.head(1).astype(str).to_dict("records")
            except Exception as exc:
                result[endpoint] = {"error": str(exc)}
    except Exception as exc:
        result["current_cb_code"] = {"error": str(exc)}

    for code in ("801010.SI", "801010.SW"):
        try:
            frame = pro.index_daily(
                ts_code=code, start_date="20260801", end_date="20260820"
            )
            result[f"index_daily_{code}"] = _summary(frame)
        except Exception as exc:
            result[f"index_daily_{code}"] = {"error": str(exc)}

    for code in ("399300.SZ", "000300.SH"):
        try:
            frame = pro.index_weight(
                index_code=code, start_date="20180101", end_date="20180131"
            )
            result[f"index_weight_{code}"] = _summary(frame)
        except Exception as exc:
            result[f"index_weight_{code}"] = {"error": str(exc)}

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "availability_probe.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("probe",))
    args = parser.parse_args()
    if args.command == "probe":
        probe()


if __name__ == "__main__":
    main()
