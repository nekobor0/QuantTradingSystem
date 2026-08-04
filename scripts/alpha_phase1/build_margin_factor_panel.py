"""Build theory-frozen abnormal margin-demand factors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


FACTORS = {
    "margin_demand_continuation_5": "A股融资盘受T+1和涨跌停约束会分批建仓；最近5日融资净需求越强，信息延续使下一月收益越高。",
    "margin_demand_continuation_10": "A股杠杆投资者对政策和主题信息可能渐进加仓；最近10日融资净需求越强，下一月收益越高。",
    "margin_flow_acceleration_5_20": "A股融资需求突然加速比稳定高余额包含更多新信息；5日净流入相对20日基线加速越强，下一月收益越高。",
    "margin_crowding_reversal_20": "A股融资盘追涨并受强平约束；过去20日融资净需求越拥挤，下一月反转压力越大。",
    "margin_balance_crowding_20": "A股融资余额快速堆积会提高踩踏风险；20日融资余额增幅越低，下一月收益越高。",
}


def build_daily(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str))
    numeric = ["rzye", "rzmre", "rzche"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["ts_code", "trade_date"]).sort_values(["ts_code", "trade_date"])
    nonnegative = frame[numeric].ge(0).all(axis=1)
    repayment_scale = frame[["rzye", "rzmre"]].max(axis=1).clip(lower=1.0)
    plausible_repayment = frame["rzche"] <= repayment_scale * 10.0
    frame["net_margin_flow"] = (frame["rzmre"] - frame["rzche"]).where(
        nonnegative & plausible_repayment
    )
    frame["rzye"] = frame["rzye"].where(frame["rzye"] >= 0)
    grouped = frame.groupby("ts_code", sort=False)
    for days in (5, 10, 20):
        frame[f"net_flow_{days}"] = grouped["net_margin_flow"].transform(
            lambda values: values.rolling(days, min_periods=max(3, days // 2)).sum()
        )
    frame["margin_flow_acceleration_5_20_raw"] = frame["net_flow_5"] - frame["net_flow_20"] * 0.25
    frame["balance_change_20"] = frame["rzye"] - grouped["rzye"].shift(20)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--margin-detail", type=Path, required=True)
    parser.add_argument("--daily-basic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    panel = pd.read_parquet(args.base_panel)
    base_columns = list(panel.columns)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    margin = build_daily(pd.read_parquet(args.margin_detail))
    margin = margin.rename(columns={"trade_date": "signal_date"})
    raw_columns = ["net_flow_5", "net_flow_10", "net_flow_20", "margin_flow_acceleration_5_20_raw", "balance_change_20"]
    panel = panel.merge(
        margin[["ts_code", "signal_date", *raw_columns]],
        on=["ts_code", "signal_date"],
        how="left",
        validate="one_to_one",
    )
    daily = pd.read_parquet(args.daily_basic, columns=["ts_code", "trade_date", "circ_mv"])
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    panel = panel.merge(daily, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    denominator = panel["circ_mv"].where(panel["circ_mv"] > 0) * 10000.0
    panel["margin_demand_continuation_5"] = panel["net_flow_5"].fillna(0.0) / denominator
    panel["margin_demand_continuation_10"] = panel["net_flow_10"].fillna(0.0) / denominator
    panel["margin_flow_acceleration_5_20"] = panel["margin_flow_acceleration_5_20_raw"].fillna(0.0) / denominator
    panel["margin_crowding_reversal_20"] = -panel["net_flow_20"].fillna(0.0) / denominator
    panel["margin_balance_crowding_20"] = -panel["balance_change_20"].fillna(0.0) / denominator
    panel = panel[base_columns + list(FACTORS)].sort_values(["ts_code", "signal_date"])
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    panel.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "coverage_before_universe_filters": {name: float(panel[name].notna().mean()) for name in FACTORS},
        "protocol": "rzmre-rzche; negative fields or rzche above 10x max(rzye,rzmre) are invalid; rolling daily sums before month-end sampling; yuan flows divided by circ_mv in 10k yuan; non-margin stocks are observed zero demand",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
