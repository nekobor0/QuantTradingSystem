"""Build the two theory-frozen V4 daily signals and T+1-open horizon labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.alpha_phase1.short_horizon import HORIZONS, calculate_short_signals


FACTORS = {
    "formulaic_012_daily": "订单量变化方向与当日收益方向不一致代表价格冲击缺乏成交确认；T日信号预测T+1起5日反转。",
    "price_volume_divergence_5d": "过去5日价格变化与成交量变化的历史标准化背离代表注意力冲击缺乏持续需求；T日信号预测T+1起5日反转。",
}


def build_symbol(symbol: str, daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    calculated = calculate_short_signals(daily)
    calculated = calculated.loc[(calculated.index >= start) & (calculated.index <= end)].copy()
    calculated.index.name = "signal_date"
    calculated = calculated.reset_index()
    calculated.insert(0, "ts_code", symbol)
    columns = [
        "ts_code", "signal_date", *FACTORS, "volatility_60", "momentum_12_1",
        *[f"forward_return_{horizon}" for horizon in HORIZONS],
        *[f"entry_tradable_{horizon}" for horizon in HORIZONS],
        *[f"exit_tradable_{horizon}" for horizon in HORIZONS],
    ]
    return calculated[columns]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-06-30")
    args = parser.parse_args()

    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    selected = json.loads(args.tdx_audit.read_text(encoding="utf-8"))["selected"]
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    writer: pq.ParquetWriter | None = None
    rows = 0
    empty_symbols = 0

    def emit(frame: pd.DataFrame) -> None:
        nonlocal writer, rows, empty_symbols
        if frame.empty:
            empty_symbols += 1
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if writer is None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
        writer.write_table(table)
        rows += len(frame)

    for number, (symbol, details) in enumerate(sorted(selected.items()), start=1):
        payload = json.loads((args.tdx_raw / details["file"]).read_text(encoding="utf-8"))
        series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(series.dates), "open": series.open, "high": series.high,
                "low": series.low, "close": series.close, "volume": series.volume,
                "factor": series.forward_factor,
            }
        )
        emit(build_symbol(symbol, daily, start, end))
        if number % 500 == 0:
            print(json.dumps({"event": "short_panel_progress", "symbols": number, "rows": rows}), flush=True)

    delisted = pd.read_parquet(args.tushare_dir / "delisted_daily.parquet").merge(
        pd.read_parquet(args.tushare_dir / "delisted_adj_factor.parquet"),
        on=["ts_code", "trade_date"],
        how="inner",
    )
    for symbol, group in delisted.groupby("ts_code", sort=True):
        daily = group.rename(columns={"trade_date": "date", "vol": "volume", "adj_factor": "factor"})
        daily["date"] = pd.to_datetime(daily["date"].astype(str))
        emit(build_symbol(str(symbol), daily, start, end))
    if writer is not None:
        writer.close()
        temporary.replace(args.output)

    metadata = {
        "version": 4,
        "rows": rows,
        "symbols_without_rows_in_window": empty_symbols,
        "start": args.start,
        "end": args.end,
        "factor_hypotheses": FACTORS,
        "primary_horizon": 5,
        "diagnostic_horizons": [1, 2, 3, 10, 20],
        "label": "T signal; enter T+1 open; horizon h exits T+(h+1) close",
        "cost": "short evaluator deducts fixed two-way 0.0005 from top-group excess",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
