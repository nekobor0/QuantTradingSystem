"""Build theory-frozen valuation and fundamental-change factors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


FACTORS = {
    "earnings_yield": "正盈利公司的市盈率倒数越高，单位价格对应的盈利越多，随后一个月的截面收益越高；亏损公司记为零盈利收益率。",
    "book_to_price": "账面价值相对市场价格越高，估值安全边际越大，随后一个月的截面收益越高。",
    "sales_to_price": "销售额相对市场价格越高，且不受短期利润确认影响，随后一个月的截面收益越高。",
    "dividend_yield": "过去十二个月现金分红收益率越高，股东实际现金回报越强，随后一个月的截面收益越高；无分红记为零。",
    "earnings_change_to_market": "过去一年总盈利相对当前市值改善越多，基本面更新越未被价格完全吸收，随后一个月收益越高。",
    "book_growth_to_market": "过去一年账面净资产相对当前市值增长越多，内生价值积累越强，随后一个月收益越高。",
    "sales_growth_to_market": "过去一年销售额相对当前市值增长越多，经营规模扩张越真实，随后一个月收益越高。",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--valuation", type=Path, required=True)
    parser.add_argument("--daily-basic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    panel = pd.read_parquet(args.base_panel)
    base_columns = list(panel.columns)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    valuation = pd.read_parquet(args.valuation)
    valuation["signal_date"] = pd.to_datetime(valuation.pop("trade_date").astype(str))
    basic = pd.read_parquet(
        args.daily_basic,
        columns=["ts_code", "trade_date", "close", "total_share", "total_mv"],
    )
    basic["signal_date"] = pd.to_datetime(basic.pop("trade_date").astype(str))
    frame = valuation.merge(basic, on=["ts_code", "signal_date"], how="left", suffixes=("", "_basic"))
    positive_pe = frame["pe_ttm"].where(frame["pe_ttm"] > 0)
    positive_pb = frame["pb"].where(frame["pb"] > 0)
    positive_ps = frame["ps_ttm"].where(frame["ps_ttm"] > 0)
    frame["earnings_yield"] = (1 / positive_pe).fillna(0.0)
    frame["book_to_price"] = 1 / positive_pb
    frame["sales_to_price"] = 1 / positive_ps
    frame["dividend_yield"] = frame["dv_ttm"].fillna(0.0) / 100
    frame["profit_proxy"] = (frame["close"] / positive_pe).fillna(0.0) * frame["total_share"]
    frame["book_proxy"] = frame["close"] / positive_pb * frame["total_share"]
    frame["sales_proxy"] = frame["close"] / positive_ps * frame["total_share"]
    frame = frame.sort_values(["ts_code", "signal_date"])
    grouped = frame.groupby("ts_code", sort=False)
    market_value = frame["total_mv_basic"].where(frame["total_mv_basic"] > 0)
    frame["earnings_change_to_market"] = (frame["profit_proxy"] - grouped["profit_proxy"].shift(12)) / market_value
    frame["book_growth_to_market"] = (frame["book_proxy"] - grouped["book_proxy"].shift(12)) / market_value
    frame["sales_growth_to_market"] = (frame["sales_proxy"] - grouped["sales_proxy"].shift(12)) / market_value
    factors = frame[["ts_code", "signal_date", *FACTORS]]
    panel = panel.merge(factors, on=["ts_code", "signal_date"], how="left")
    panel = panel[base_columns + list(FACTORS)].sort_values(["ts_code", "signal_date"])
    panel.to_parquet(args.output, index=False)
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "coverage_before_universe_filters": {
            factor: float(panel[factor].notna().mean()) for factor in FACTORS
        },
        "protocol": "month-end daily_basic only; 12-month changes use data frozen before evaluation; non-positive or unavailable PE maps to zero earnings yield",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
