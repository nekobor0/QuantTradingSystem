"""Build theory-frozen money-flow and point-in-time holder-count factors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


FACTORS = {
    "institutional_flow_20": "大单与特大单持续净买入代表知情资金的信息逐步扩散，随后一个月的截面收益更高。",
    "institutional_flow_acceleration": "近五日机构型净流入相对近二十日基线加速，代表尚未被价格完全吸收的新信息，随后一个月收益更高。",
    "retail_flow_reversal_5": "小单资金在五日内异常净买入代表散户追涨需求，随后一个月发生反转。",
    "smart_money_divergence_20": "大单净买入同时小单净卖出代表筹码从散户向知情资金转移，随后一个月收益更高。",
    "institutional_flow_consistency_20": "大单净流入出现得越持续而非集中在单日，信息扩散越可靠，随后一个月收益更高。",
    "holder_concentration_change": "公告可见的股东户数下降代表筹码集中，公告后下一月的截面收益更高。",
    "holder_concentration_level": "每户持有的自由流通股越多代表筹码越集中，公告后下一月的截面收益更高。",
}


def rolling_sum(frame: pd.DataFrame, column: str, window: int, minimum: int) -> pd.Series:
    return frame.groupby("ts_code", sort=False)[column].transform(
        lambda values: values.rolling(window, min_periods=minimum).sum()
    )


def build_moneyflow(path: Path, signal_dates: pd.Series) -> pd.DataFrame:
    columns = [
        "ts_code", "trade_date", "buy_sm_amount", "sell_sm_amount",
        "buy_md_amount", "sell_md_amount", "buy_lg_amount", "sell_lg_amount",
        "buy_elg_amount", "sell_elg_amount",
    ]
    frame = pd.read_parquet(path, columns=columns)
    frame["signal_date"] = pd.to_datetime(frame.pop("trade_date").astype(str))
    frame = frame.sort_values(["ts_code", "signal_date"])
    amounts = [column for column in columns if column.endswith("_amount")]
    frame[amounts] = frame[amounts].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    frame["large_net"] = (
        frame["buy_lg_amount"] + frame["buy_elg_amount"]
        - frame["sell_lg_amount"] - frame["sell_elg_amount"]
    )
    frame["small_net"] = frame["buy_sm_amount"] - frame["sell_sm_amount"]
    frame["activity"] = frame[amounts].sum(axis=1)
    for window, minimum in ((5, 3), (20, 12)):
        for column in ("large_net", "small_net", "activity"):
            frame[f"{column}_{window}"] = rolling_sum(frame, column, window, minimum)
    activity_5 = frame["activity_5"].where(frame["activity_5"] > 0)
    activity_20 = frame["activity_20"].where(frame["activity_20"] > 0)
    frame["institutional_flow_20"] = frame["large_net_20"] / activity_20
    frame["institutional_flow_acceleration"] = (
        frame["large_net_5"] / activity_5 - frame["large_net_20"] / activity_20
    )
    frame["retail_flow_reversal_5"] = -frame["small_net_5"] / activity_5
    frame["smart_money_divergence_20"] = (
        frame["large_net_20"] - frame["small_net_20"]
    ) / activity_20
    positive = frame["large_net"].gt(0).where(frame["activity"].gt(0)).astype(float)
    frame["institutional_flow_consistency_20"] = positive.groupby(frame["ts_code"], sort=False).transform(
        lambda values: values.rolling(20, min_periods=12).mean()
    )
    factors = [name for name in FACTORS if name in frame]
    wanted = set(pd.to_datetime(signal_dates))
    return frame.loc[frame["signal_date"].isin(wanted), ["ts_code", "signal_date", *factors]]


def build_holder(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame["announcement_date"] = pd.to_datetime(frame.pop("ann_date").astype(str), errors="coerce")
    frame["report_date"] = pd.to_datetime(frame.pop("end_date").astype(str), errors="coerce")
    frame["holder_num"] = pd.to_numeric(frame["holder_num"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "announcement_date", "report_date", "holder_num"])
    frame = frame.sort_values(["ts_code", "report_date", "announcement_date"]).drop_duplicates(
        ["ts_code", "report_date"], keep="last"
    )
    prior = frame.groupby("ts_code", sort=False)["holder_num"].shift(1)
    frame["holder_concentration_change"] = -np.log(
        frame["holder_num"].where(frame["holder_num"] > 0) / prior.where(prior > 0)
    )
    return frame[["ts_code", "announcement_date", "holder_num", "holder_concentration_change"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--moneyflow", type=Path, required=True)
    parser.add_argument("--holdernumber", type=Path, required=True)
    parser.add_argument("--daily-basic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    panel = pd.read_parquet(args.base_panel)
    base_columns = list(panel.columns)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    flow = build_moneyflow(args.moneyflow, panel["signal_date"].drop_duplicates())
    panel = panel.merge(flow, on=["ts_code", "signal_date"], how="left")

    holder = build_holder(args.holdernumber)
    panel = pd.merge_asof(
        panel.sort_values(["signal_date", "ts_code"]),
        holder.sort_values(["announcement_date", "ts_code"]),
        left_on="signal_date",
        right_on="announcement_date",
        by="ts_code",
        direction="backward",
    ).drop(columns="announcement_date")
    daily = pd.read_parquet(args.daily_basic, columns=["ts_code", "trade_date", "free_share"])
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    panel = panel.merge(daily, on=["ts_code", "signal_date"], how="left")
    panel["holder_concentration_level"] = np.log(
        panel["free_share"].where(panel["free_share"] > 0) * 10000
        / panel["holder_num"].where(panel["holder_num"] > 0)
    )
    panel = panel.drop(columns=["holder_num", "free_share"])
    panel = panel[base_columns + list(FACTORS)].sort_values(["ts_code", "signal_date"])
    panel.to_parquet(args.output, index=False)
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "coverage_before_universe_filters": {
            factor: float(panel[factor].notna().mean()) for factor in FACTORS
        },
        "holder_protocol": "deduplicate by report date using latest announcement; use only announcements on or before signal date",
        "moneyflow_protocol": "daily rolling windows computed before month-end sampling; monetary amounts normalized by total classified activity",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
