"""Build PIT unlock, repurchase, and actual holder-trade factors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


FACTORS = {
    "repurchase_execution_60": "A股回购意向不等于执行；最近60日已实施或完成的实际回购金额占流通市值越高，下一月收益越高。",
    "repurchase_completion_120": "A股散户可能低估管理层真金白银完成回购的信号；最近120日完成回购强度越高，下一月收益越高。",
    "holder_net_purchase_60": "A股重要股东实际增持比计划公告更可信；最近60日实际净增持比例越高，下一月收益越高。",
    "holder_net_purchase_120": "A股内部人交易信息扩散较慢；最近120日重要股东持续净增持比例越高，下一月收益越高。",
    "holder_conviction_120": "A股控股股东和高管的实际增持信息优势强于普通持有人；加权后的120日净增持越高，下一月收益越高。",
}


def _repurchase_scores(raw: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    frame = raw.copy()
    frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").where(lambda values: values > 0, 0.0)
    frame = frame.dropna(subset=["ts_code", "ann_date"])
    plan_fields = ["ts_code", "exp_date", "low_limit", "high_limit"]
    frame["plan_key"] = frame[plan_fields].fillna("<NA>").astype(str).agg("|".join, axis=1)
    rows = []
    for date in dates:
        known = frame[frame["ann_date"] <= date].sort_values("ann_date")
        row = pd.DataFrame({"ts_code": known["ts_code"].unique()})
        row["signal_date"] = date
        for days, name, processes in (
            (60, "repurchase_execution_60", {"实施", "完成"}),
            (120, "repurchase_completion_120", {"完成"}),
        ):
            recent = known[known["ann_date"] > date - pd.Timedelta(days=days)]
            recent = recent.drop_duplicates("plan_key", keep="last")
            values = recent.loc[recent["proc"].isin(processes)].groupby("ts_code")["amount"].sum()
            row[name] = row["ts_code"].map(values).fillna(0.0)
        rows.append(row)
    return pd.concat(rows, ignore_index=True)


def _holder_scores(raw: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    frame = raw.copy()
    frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
    frame["change_ratio"] = pd.to_numeric(frame["change_ratio"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "ann_date", "change_ratio", "in_de"])
    frame["signed_ratio"] = np.where(frame["in_de"].eq("IN"), 1.0, -1.0) * frame["change_ratio"].abs()
    holder_text = frame["holder_type"].fillna("").astype(str)
    frame["conviction_weight"] = np.where(
        holder_text.str.contains("控股|实际控制|高管|董监高", regex=True), 1.5, 1.0
    )
    rows = []
    for date in dates:
        row = pd.DataFrame({"ts_code": frame["ts_code"].unique()})
        row["signal_date"] = date
        for days, name in ((60, "holder_net_purchase_60"), (120, "holder_net_purchase_120")):
            recent = frame[(frame["ann_date"] <= date) & (frame["ann_date"] > date - pd.Timedelta(days=days))]
            values = recent.groupby("ts_code")["signed_ratio"].sum()
            row[name] = row["ts_code"].map(values).fillna(0.0)
        recent = frame[(frame["ann_date"] <= date) & (frame["ann_date"] > date - pd.Timedelta(days=120))].copy()
        recent["weighted_ratio"] = recent["signed_ratio"] * recent["conviction_weight"]
        values = recent.groupby("ts_code")["weighted_ratio"].sum()
        row["holder_conviction_120"] = row["ts_code"].map(values).fillna(0.0)
        rows.append(row)
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    panel = pd.read_parquet(args.base_panel)
    base_columns = list(panel.columns)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    dates = sorted(pd.Timestamp(value) for value in panel["signal_date"].unique())
    daily = pd.read_parquet(
        args.tushare_dir / "daily_basic_month_end.parquet",
        columns=["ts_code", "trade_date", "free_share", "circ_mv"],
    )
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    panel = panel.merge(daily, on=["ts_code", "signal_date"], how="left", validate="one_to_one")

    repurchase = _repurchase_scores(pd.read_parquet(args.tushare_dir / "repurchase.parquet"), dates)
    panel = panel.merge(repurchase, on=["ts_code", "signal_date"], how="left")
    for name in ("repurchase_execution_60", "repurchase_completion_120"):
        panel[name] = panel[name].fillna(0.0) / (
            panel["circ_mv"].where(panel["circ_mv"] > 0) * 10000.0
        )

    holder = _holder_scores(pd.read_parquet(args.tushare_dir / "stk_holdertrade.parquet"), dates)
    panel = panel.merge(holder, on=["ts_code", "signal_date"], how="left")
    for name in ("holder_net_purchase_60", "holder_net_purchase_120", "holder_conviction_120"):
        panel[name] = panel[name].fillna(0.0)

    panel = panel[base_columns + list(FACTORS)].sort_values(["ts_code", "signal_date"])
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    panel.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "coverage_before_universe_filters": {name: float(panel[name].notna().mean()) for name in FACTORS},
        "protocol": {
            "repurchase": "latest disclosure per approximate plan key; only implementation/completion counted; cumulative amounts never summed across progress notices",
            "holdertrade": "actual IN/DE rows signed by direction; no-event is an observed zero rather than missing data",
        },
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
