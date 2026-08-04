"""Build the frozen monthly Phase 1 factor panel from cached research data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant_trading_system.research.alpha_phase1 import parse_research_series


FACTORS = {
    "reversal_1m": "过去20日涨幅越极端，未来一月越可能因短期过度反应而反转。",
    "momentum_12_1": "剔除最近一月后，过去一年赢家因信息扩散不足继续跑赢。",
    "momentum_6_1": "剔除最近一月后，过去半年趋势因机构缓慢调仓继续。",
    "low_max_return": "近20日出现彩票型单日暴涨的股票随后收益更低。",
    "low_skew": "近期正偏度越高的股票因彩票偏好溢价越高、未来收益越低。",
    "volume_shock_reversal": "近期成交量相对长期异常放大代表注意力冲击，随后回撤。",
    "price_volume_divergence": "价格上涨但量能变化未确认时，趋势更容易反转。",
    "liquidity_shock_reversal": "近期单位成交额价格冲击异常上升后，流动性压力会均值回归。",
    "overnight_reversal": "隔夜跳空买入压力主要承载噪声交易，未来收益反转。",
    "intraday_reversal": "日内持续追涨代表短期需求冲击，未来收益反转。",
    "close_location_reversal": "频繁收在日内高位代表收盘追价，未来收益反转。",
    "range_shock_reversal": "近期振幅相对长期异常放大代表分歧冲击，未来收益反转。",
}


def calculate_daily(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values("date").set_index("date")
    adjusted = frame["close"] * frame["factor"]
    adjusted_open = frame["open"] * frame["factor"]
    ret = adjusted.pct_change(fill_method=None)
    log_volume = np.log1p(frame["volume"])
    illiquidity = ret.abs() / frame["amount"].replace(0, np.nan)
    location = (frame["close"] - frame["low"]) / (frame["high"] - frame["low"]).replace(0, np.nan)
    daily_range = (frame["high"] - frame["low"]) / frame["close"]
    output = pd.DataFrame(index=frame.index)
    output["adjusted_close"] = adjusted
    output["reversal_1m"] = -adjusted.pct_change(20, fill_method=None)
    output["momentum_12_1"] = adjusted.shift(20) / adjusted.shift(252) - 1
    output["momentum_6_1"] = adjusted.shift(20) / adjusted.shift(126) - 1
    output["low_max_return"] = -ret.rolling(20).max()
    output["low_skew"] = -ret.rolling(20).skew()
    output["volume_shock_reversal"] = -np.log(
        frame["volume"].rolling(20).mean() / frame["volume"].rolling(120).mean()
    )
    output["price_volume_divergence"] = -(ret.rolling(20).sum() - log_volume.diff(20))
    output["liquidity_shock_reversal"] = -np.log(
        illiquidity.rolling(20).mean() / illiquidity.rolling(120).mean()
    )
    output["overnight_reversal"] = -(adjusted_open / adjusted.shift(1) - 1).rolling(20).mean()
    output["intraday_reversal"] = -(frame["close"] / frame["open"] - 1).rolling(20).mean()
    output["close_location_reversal"] = -location.rolling(20).mean()
    output["range_shock_reversal"] = -np.log(
        daily_range.rolling(20).mean() / daily_range.rolling(120).mean()
    )
    output["volatility_60"] = ret.rolling(60).std()
    return output


def sample_symbol(
    symbol: str,
    daily: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    entry_1: dict[pd.Timestamp, pd.Timestamp],
    exit_1: dict[pd.Timestamp, pd.Timestamp],
    entry_3: dict[pd.Timestamp, pd.Timestamp],
    exit_3: dict[pd.Timestamp, pd.Timestamp],
) -> pd.DataFrame:
    calculated = calculate_daily(daily)
    ordered = daily.sort_values("date").set_index("date")
    previous_close = ordered["close"].shift(1)
    absolute_return = (ordered["close"] / previous_close - 1).abs()
    one_price = (
        ordered[["open", "high", "low", "close"]].max(axis=1)
        == ordered[["open", "high", "low", "close"]].min(axis=1)
    )
    tradable = (ordered["volume"] > 0) & ~(one_price & (absolute_return >= 0.045))
    sampled = calculated.reindex(signal_dates)
    sampled.index.name = "signal_date"
    sampled = sampled.reset_index()
    sampled.insert(0, "ts_code", symbol)
    exit_prices = calculated["adjusted_close"]
    entry_prices = ordered["open"] * ordered["factor"]
    sampled["forward_return"] = [
        exit_prices.get(exit_1[date], np.nan) / entry_prices.get(entry_1[date], np.nan) - 1
        if (
            date in exit_1
            and bool(tradable.get(entry_1[date], False))
            and bool(tradable.get(exit_1[date], False))
        )
        else np.nan
        for date in signal_dates
    ]
    sampled["entry_1_tradable"] = [
        bool(tradable.get(entry_1[date], False)) if date in entry_1 else False
        for date in signal_dates
    ]
    sampled["exit_1_tradable"] = [
        bool(tradable.get(exit_1[date], False)) if date in exit_1 else False
        for date in signal_dates
    ]
    sampled["forward_return_delay2"] = [
        exit_prices.get(exit_3[date], np.nan) / entry_prices.get(entry_3[date], np.nan) - 1
        if (
            date in exit_3
            and bool(tradable.get(entry_3[date], False))
            and bool(tradable.get(exit_3[date], False))
        )
        else np.nan
        for date in signal_dates
    ]
    return sampled


def calendar_maps(calendar: pd.DataFrame, start: str, end: str):
    opens = pd.to_datetime(
        calendar.loc[calendar["is_open"].astype(str) == "1", "cal_date"].astype(str)
    ).sort_values().tolist()
    month_ends = pd.Series(opens).groupby(pd.Series(opens).dt.to_period("M")).max().tolist()
    signals = [date for date in month_ends if pd.Timestamp(start) <= date <= pd.Timestamp(end)]
    positions = {date: index for index, date in enumerate(opens)}
    entry_1, exit_1, entry_3, exit_3 = {}, {}, {}, {}
    for current, following in zip(signals, signals[1:]):
        if positions[current] + 3 < len(opens) and positions[following] + 3 < len(opens):
            entry_1[current] = opens[positions[current] + 1]
            exit_1[current] = opens[positions[following] + 1]
            entry_3[current] = opens[positions[current] + 3]
            exit_3[current] = opens[positions[following] + 3]
    return signals, entry_1, exit_1, entry_3, exit_3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--start", default="2018-07-31")
    parser.add_argument("--end", default="2026-06-30")
    args = parser.parse_args()

    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    maps = calendar_maps(calendar, args.start, args.end)
    signals = maps[0]
    audit = json.loads(args.tdx_audit.read_text(encoding="utf-8"))
    selected = audit["selected"]
    writer: pq.ParquetWriter | None = None
    rows = 0
    temporary_output = args.output.with_suffix(args.output.suffix + ".tmp")

    def emit(panel: pd.DataFrame) -> None:
        nonlocal writer, rows
        table = pa.Table.from_pandas(panel, preserve_index=False)
        if writer is None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            writer = pq.ParquetWriter(temporary_output, table.schema, compression="zstd")
        writer.write_table(table)
        rows += len(panel)

    for number, (symbol, details) in enumerate(sorted(selected.items()), start=1):
        payload = json.loads((args.tdx_raw / details["file"]).read_text(encoding="utf-8"))
        series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(series.dates), "open": series.open, "high": series.high,
                "low": series.low, "close": series.close, "volume": series.volume,
                "amount": series.amount_wan, "factor": series.forward_factor,
            }
        )
        emit(sample_symbol(symbol, daily, *maps))
        if number % 500 == 0:
            print(json.dumps({"event": "panel_progress", "current_symbols": number}), flush=True)

    delisted_daily = pd.read_parquet(args.tushare_dir / "delisted_daily.parquet")
    delisted_factor = pd.read_parquet(args.tushare_dir / "delisted_adj_factor.parquet")
    merged = delisted_daily.merge(delisted_factor, on=["ts_code", "trade_date"], how="inner")
    for symbol, group in merged.groupby("ts_code", sort=True):
        daily = group.rename(columns={"trade_date": "date", "vol": "volume", "adj_factor": "factor"})
        daily["date"] = pd.to_datetime(daily["date"].astype(str))
        emit(sample_symbol(str(symbol), daily, *maps))
    if writer is not None:
        writer.close()
        temporary_output.replace(args.output)
    metadata = {
        "version": 1, "rows": rows, "signal_months": len(signals),
        "first_signal": str(signals[0].date()), "last_signal": str(signals[-1].date()),
        "factor_hypotheses": FACTORS,
        "label": "signal month-end close; enter next trading-day open, exit next month's next-trading-day close",
        "label_tradability": "entry and exit require positive volume; one-price days with absolute close return >=4.5% are unavailable",
        "delay2_label": "entry open and exit close shifted two additional trading days",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
