"""Build a frozen monthly-persistence adaptation of published formulaic alphas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from build_factor_panel import calendar_maps
from quant_trading_system.research.alpha_phase1 import parse_research_series


FACTORS = {
    "formulaic_006": "开盘价与成交量的短期相关性越高越可能代表拥挤交易，持续出现后未来收益越低。",
    "formulaic_012": "价格变化与成交量变化方向不一致代表短期冲击缺乏确认，持续出现后价格更易反转。",
    "formulaic_018": "日内价差、价差波动与开收盘共振越强，短期拥挤越严重，持续出现后未来收益越低。",
    "formulaic_021": "短均线偏离长均线及异常成交量共同刻画短期状态，持续处于超卖状态的股票随后收益更高。",
    "formulaic_023": "价格突破二十日高位后的高点回撤信号持续出现，代表突破失败，随后收益更低。",
    "formulaic_024": "长期趋势平缓时价格偏离百日低点会均值回归，趋势较强时三日变化会反转。",
    "formulaic_026": "成交量与高价位置的时序排名持续高度相关代表追价拥挤，随后收益更低。",
    "formulaic_033": "收盘相对开盘越弱代表日内卖压，持续卖压被过度定价后未来收益更高。",
    "formulaic_041": "几何中间价低于成交均价代表成交重心偏高，持续追价后未来收益更低。",
    "formulaic_046": "二十日至十日与十日至当前的趋势加速度发生极端变化时，价格随后均值回归。",
    "formulaic_049": "趋势加速度显著转负时保留反弹信号，否则对单日价格变化做反转。",
    "formulaic_051": "较温和的趋势转负阈值捕捉早期反弹，否则对单日价格变化做反转。",
    "formulaic_053": "收盘在日内区间的位置快速恶化代表卖压加速，随后价格更可能反弹。",
    "formulaic_054": "开高低收的非线性位置关系刻画尾盘价格压力，持续压力随后均值回归。",
    "formulaic_101": "收盘相对开盘的涨幅经日内振幅归一化后若持续为正，代表可延续的日内动量。",
}


def ts_rank(values: pd.Series, window: int) -> pd.Series:
    return values.rolling(window).rank(pct=True)


def calculate(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values("date").set_index("date")
    factor = frame["factor"]
    close = frame["close"] * factor
    open_ = frame["open"] * factor
    high = frame["high"] * factor
    low = frame["low"] * factor
    volume = frame["volume"]
    vwap = frame["amount"] * 10000 / volume.replace(0, np.nan) * factor
    delta_close = close.diff()
    mean8, mean2 = close.rolling(8).mean(), close.rolling(2).mean()
    std8, adv20 = close.rolling(8).std(), volume.rolling(20).mean()
    acceleration = (close.shift(20) - close.shift(10)) / 10 - (close.shift(10) - close) / 10
    volume_rank5, high_rank5 = ts_rank(volume, 5), ts_rank(high, 5)
    raw = pd.DataFrame(index=frame.index)
    raw["formulaic_006"] = -open_.rolling(10).corr(volume)
    raw["formulaic_012"] = np.sign(volume.diff()) * -delta_close
    raw["formulaic_018"] = -(
        (close - open_).abs().rolling(5).std() + (close - open_) + close.rolling(10).corr(open_)
    )
    raw["formulaic_021"] = np.select(
        [mean8 + std8 < mean2, mean2 < mean8 - std8, volume / adv20 >= 1],
        [-1.0, 1.0, 1.0],
        default=-1.0,
    )
    raw["formulaic_023"] = np.where(high.rolling(20).mean() < high, -high.diff(2), 0.0)
    trend = close.rolling(100).mean().diff(100) / close.shift(100)
    raw["formulaic_024"] = np.where(
        trend <= 0.05, -(close - close.rolling(100).min()), -close.diff(3)
    )
    raw["formulaic_026"] = -volume_rank5.rolling(5).corr(high_rank5).rolling(3).max()
    raw["formulaic_033"] = open_ / close - 1
    raw["formulaic_041"] = np.sqrt(high * low) - vwap
    raw["formulaic_046"] = np.select(
        [acceleration > 0.25, acceleration < 0], [-1.0, 1.0], default=-delta_close
    )
    raw["formulaic_049"] = np.where(acceleration < -0.1, 1.0, -delta_close)
    raw["formulaic_051"] = np.where(acceleration < -0.05, 1.0, -delta_close)
    position = ((close - low) - (high - close)) / (close - low).replace(0, np.nan)
    raw["formulaic_053"] = -position.diff(9)
    raw["formulaic_054"] = -(
        (low - close) * open_.pow(5) / ((low - high) * close.pow(5)).replace(0, np.nan)
    )
    raw["formulaic_101"] = (close - open_) / (high - low + 0.001)
    return raw.rolling(20, min_periods=12).mean()


def sample(symbol: str, daily: pd.DataFrame, signals: list[pd.Timestamp]) -> pd.DataFrame:
    output = calculate(daily).reindex(signals)
    output.index.name = "signal_date"
    output = output.reset_index()
    output.insert(0, "ts_code", symbol)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--start", default="2018-07-31")
    parser.add_argument("--end", default="2026-06-30")
    args = parser.parse_args()

    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    signals = calendar_maps(calendar, args.start, args.end)[0]
    selected = json.loads(args.tdx_audit.read_text(encoding="utf-8"))["selected"]
    temporary = args.output.with_name(args.output.stem + "_signals.parquet")
    writer: pq.ParquetWriter | None = None

    def emit(frame: pd.DataFrame) -> None:
        nonlocal writer
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
        writer.write_table(table)

    for number, (symbol, details) in enumerate(sorted(selected.items()), start=1):
        payload = json.loads((args.tdx_raw / details["file"]).read_text(encoding="utf-8"))
        series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
        daily = pd.DataFrame({
            "date": pd.to_datetime(series.dates), "open": series.open, "high": series.high,
            "low": series.low, "close": series.close, "volume": series.volume,
            "amount": series.amount_wan, "factor": series.forward_factor,
        })
        emit(sample(symbol, daily, signals))
        if number % 500 == 0:
            print(json.dumps({"event": "formulaic_progress", "symbols": number}), flush=True)

    delisted = pd.read_parquet(args.tushare_dir / "delisted_daily.parquet").merge(
        pd.read_parquet(args.tushare_dir / "delisted_adj_factor.parquet"),
        on=["ts_code", "trade_date"],
        how="inner",
    )
    for symbol, group in delisted.groupby("ts_code", sort=True):
        daily = group.rename(columns={"trade_date": "date", "vol": "volume", "adj_factor": "factor"})
        daily["date"] = pd.to_datetime(daily["date"].astype(str))
        emit(sample(str(symbol), daily, signals))
    if writer is not None:
        writer.close()

    base = pd.read_parquet(args.base_panel)
    base["signal_date"] = pd.to_datetime(base["signal_date"])
    factors = pd.read_parquet(temporary)
    panel = base.merge(factors, on=["ts_code", "signal_date"], how="left")
    panel.to_parquet(args.output, index=False)
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "adaptation": "20-day mean of each daily formula to align with monthly prediction; whole-expression outer ranks omitted because evaluation ranks each monthly cross-section",
        "source": "Kakushadze (2016), 101 Formulaic Alphas, arXiv:1601.00991",
        "coverage_before_universe_filters": {
            factor: float(panel[factor].notna().mean()) for factor in FACTORS
        },
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
