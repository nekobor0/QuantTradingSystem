"""Evaluate the two frozen V3 daily factors with exact daily controls and ST flags."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.classified_evaluation import evaluate_short_factor
from quant_trading_system.research.alpha_phase1.long_only_evaluation import CONTROL_COLUMNS, neutralize
from quant_trading_system.research.alpha_phase1.short_horizon import HORIZONS


FACTORS = {
    "formulaic_012_daily": "订单量变化方向与当日收益方向不一致代表价格冲击缺乏成交确认；T日信号预测T+1起5日反转。",
    "price_volume_divergence_5d": "过去5日价格变化与成交量变化的历史标准化背离代表注意力冲击缺乏持续需求；T日信号预测T+1起5日反转。",
}


def assign_industry(frame: pd.DataFrame, members: pd.DataFrame) -> pd.Series:
    members = members.copy()
    members["in_date"] = members["in_date"].fillna("").astype(str)
    members["out_date"] = members["out_date"].fillna("").astype(str)
    result = np.empty(len(frame), dtype=object)
    result[:] = None
    codes = frame["ts_code"].astype(str)
    for date, positions in frame.groupby("signal_date", sort=False).indices.items():
        text = pd.Timestamp(date).strftime("%Y%m%d")
        active = members[
            (members["in_date"] <= text)
            & ((members["out_date"] == "") | (members["out_date"] > text))
        ].sort_values(["ts_code", "in_date", "l1_code"]).drop_duplicates("ts_code", keep="last")
        mapping = active.set_index("ts_code")["l1_code"]
        result[positions] = codes.iloc[positions].map(mapping).to_numpy()
    return pd.Series(result, index=frame.index, dtype="object")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pure-output", type=Path, required=True)
    parser.add_argument("--version", type=int, default=3)
    args = parser.parse_args()

    panel_columns = [
        "ts_code", "signal_date", *FACTORS, "volatility_60", "momentum_12_1",
        *[f"forward_return_{horizon}" for horizon in HORIZONS],
        *[f"entry_tradable_{horizon}" for horizon in HORIZONS],
        *[f"exit_tradable_{horizon}" for horizon in HORIZONS],
    ]
    frame = pd.read_parquet(args.panel, columns=panel_columns)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    basic = pd.read_parquet(
        args.tushare_dir / "daily_basic_full.parquet",
        columns=["ts_code", "trade_date", "circ_mv", "turnover_rate_f"],
    )
    basic["signal_date"] = pd.to_datetime(basic.pop("trade_date").astype(str))
    frame = frame.merge(basic, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame["log_circ_mv"] = np.log(frame["circ_mv"].where(frame["circ_mv"] > 0))
    frame["log_turnover"] = np.log1p(frame["turnover_rate_f"].where(frame["turnover_rate_f"] >= 0))

    stocks = pd.read_parquet(
        args.tushare_dir / "stock_basic.parquet",
        columns=["ts_code", "list_date", "delist_date"],
    ).drop_duplicates("ts_code", keep="last")
    stocks["list_date"] = pd.to_datetime(stocks["list_date"], errors="coerce")
    stocks["delist_date"] = pd.to_datetime(stocks["delist_date"], errors="coerce")
    frame = frame.merge(stocks, on="ts_code", how="left", validate="many_to_one")
    frame["pit_active"] = (frame["list_date"] <= frame["signal_date"]) & (
        frame["delist_date"].isna() | (frame["signal_date"] < frame["delist_date"])
    )

    st_manifest = json.loads(
        (args.tushare_dir / "stock_st_full_available_manifest.json").read_text(encoding="utf-8")
    )
    excluded_st_dates = pd.to_datetime(st_manifest["excluded_source_gap_days"])
    st = pd.read_parquet(
        args.tushare_dir / "stock_st_full_available.parquet", columns=["ts_code", "trade_date"]
    )
    st["signal_date"] = pd.to_datetime(st.pop("trade_date").astype(str))
    st = st.drop_duplicates(["ts_code", "signal_date"]).assign(is_st=True)
    frame = frame.merge(st, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame["is_st"] = frame["is_st"].fillna(False).astype(bool)
    frame["st_date_available"] = ~frame["signal_date"].isin(excluded_st_dates)
    frame["l1_code"] = assign_industry(
        frame, pd.read_parquet(args.tushare_dir / "index_members_sw2021.parquet")
    )
    frame["eligible_quality"] = (
        frame["pit_active"]
        & frame["st_date_available"]
        & frame["circ_mv"].gt(0)
        & frame["forward_return_5"].notna()
        & frame["entry_tradable_5"].astype(bool)
        & frame["exit_tradable_5"].astype(bool)
    )
    frame["eligible_evaluation"] = frame["eligible_quality"] & frame[
        [*CONTROL_COLUMNS, "l1_code"]
    ].notna().all(axis=1)

    results = {}
    pure_frame = frame[["ts_code", "signal_date"]].copy()
    for factor, hypothesis in FACTORS.items():
        pure_name = f"pure_{factor}"
        frame[pure_name] = neutralize(frame, factor).astype("float32")
        pure_frame[pure_name] = frame[pure_name]
        results[factor] = evaluate_short_factor(frame, factor, pure_name, hypothesis)
        print(json.dumps({"factor": factor, "pass": results[factor]["passes_all_gates"]}, ensure_ascii=False), flush=True)
    pure_frame.to_parquet(args.pure_output, index=False, compression="zstd")
    payload = {
        "version": args.version,
        "channel": "short_horizon",
        "entry_price": "T+1 open" if args.version >= 4 else "T+1 close",
        "rows": len(frame),
        "eligible_rows": int(frame["eligible_evaluation"].sum()),
        "results": results,
        "admissions": [name for name, result in results.items() if result["passes_all_gates"]],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"admissions": payload["admissions"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
