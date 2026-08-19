"""Resumable historical dividend-event backfill for the research simulator.

Eastmoney's semiannual all-market tables are used for efficient bulk history.
Tushare remains the daily incremental source and supplies pay dates.  No token
or response containing credentials is logged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd


def strategy_universe(signal_path: Path, start: str = "2017-12-01") -> set[str]:
    columns = ["signal_date", "ts_code", "eligible", "dividend_yield", "value_composite", "amihud20"]
    signal = pd.read_parquet(signal_path, columns=columns)
    signal = signal[signal["signal_date"].ge(pd.Timestamp(start))].copy()
    for column in ("value_composite", "amihud20", "dividend_yield"):
        signal["r_" + column] = signal.groupby("signal_date")[column].rank(pct=True)
    signal["balanced"] = 0.4 * signal["r_value_composite"] + 0.3 * signal["r_amihud20"] + 0.3 * signal["r_dividend_yield"]
    dividend = (
        signal[signal["eligible"].fillna(False) & signal["dividend_yield"].ge(0.05)]
        .sort_values(["signal_date", "dividend_yield"], ascending=[True, False])
        .groupby("signal_date")
        .head(100)
    )
    voltrend = (
        signal[signal["eligible"].fillna(False) & signal["balanced"].notna()]
        .sort_values(["signal_date", "balanced"], ascending=[True, False])
        .groupby("signal_date")
        .head(100)
    )
    return set(dividend["ts_code"]).union(voltrend["ts_code"])


def report_periods(start_year: int, end_year: int) -> list[str]:
    return [f"{year}{suffix}" for year in range(start_year, end_year + 1) for suffix in ("0630", "1231")]


def _ts_code(code: object) -> str:
    value = str(code).split(".")[0].zfill(6)
    suffix = "SH" if value.startswith(("5", "6", "9")) else "BJ" if value.startswith(("4", "8")) else "SZ"
    return f"{value}.{suffix}"


def normalize_eastmoney(frame: pd.DataFrame, report_period: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    mapping = {
        "代码": "code",
        "现金分红-现金分红比例": "cash_per_10_shares",
        "股权登记日": "record_date",
        "除权除息日": "ex_date",
        "方案进度": "div_proc",
        "最新公告日期": "ann_date",
    }
    missing = set(mapping).difference(frame.columns)
    if missing:
        raise ValueError(f"Eastmoney dividend schema missing: {sorted(missing)}")
    output = frame[list(mapping)].rename(columns=mapping).copy()
    output["ts_code"] = output.pop("code").map(_ts_code)
    output["end_date"] = report_period
    output["cash_div_tax"] = pd.to_numeric(output.pop("cash_per_10_shares"), errors="coerce") / 10.0
    for column in ("record_date", "ex_date", "ann_date"):
        output[column] = pd.to_datetime(output[column], errors="coerce")
    output["pay_date"] = pd.NaT
    output["source"] = "eastmoney_via_akshare"
    output = output[
        output["div_proc"].astype(str).str.contains("实施", na=False)
        & output["record_date"].notna()
        & output["cash_div_tax"].fillna(0).gt(0)
    ]
    return output[
        ["ts_code", "end_date", "ann_date", "div_proc", "cash_div_tax", "record_date", "ex_date", "pay_date", "source"]
    ]


def _fetch_period(period: str, cache_path: Path, retries: int = 4) -> pd.DataFrame:
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    import akshare as ak

    error: Exception | None = None
    for attempt in range(retries):
        try:
            frame = ak.stock_fhps_em(date=period)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(cache_path, index=False)
            return frame
        except Exception as exc:  # transient public endpoint failures are retried
            error = exc
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"dividend period {period} failed after {retries} attempts: {type(error).__name__}")


def run(signal_path: Path, output: Path, start_year: int = 2017, end_year: int = 2026) -> dict:
    universe = strategy_universe(signal_path)
    cache = output.parent / "dividend_history_cache"
    frames: list[pd.DataFrame] = []
    period_rows: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for period in report_periods(start_year, end_year):
        try:
            raw = _fetch_period(period, cache / f"{period}.parquet")
            normalized = normalize_eastmoney(raw, period)
            normalized = normalized[normalized["ts_code"].isin(universe)]
            frames.append(normalized)
            period_rows[period] = len(normalized)
        except Exception as exc:
            errors.append({"period": period, "error": f"{type(exc).__name__}: {exc}"})
    if not frames:
        raise RuntimeError("No dividend history was fetched")
    history = pd.concat(frames, ignore_index=True)
    history = history.drop_duplicates(["ts_code", "record_date", "cash_div_tax"], keep="last")
    history = history.sort_values(["record_date", "ts_code"]).reset_index(drop=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    history.to_parquet(tmp, index=False)
    tmp.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "source": "Eastmoney RPT_SHAREBONUS_DET via AKShare stock_fhps_em",
        "strategy_universe_size": len(universe),
        "periods_requested": len(report_periods(start_year, end_year)),
        "periods_completed": len(period_rows),
        "events": len(history),
        "symbols_with_events": int(history["ts_code"].nunique()),
        "min_record_date": history["record_date"].min().strftime("%Y-%m-%d"),
        "max_record_date": history["record_date"].max().strftime("%Y-%m-%d"),
        "sha256": digest,
        "period_rows": period_rows,
        "errors": errors,
        "limitations": [
            "Semiannual report-period bulk source can omit quarterly or special dividends.",
            "Pay date is absent and must be supplemented by Tushare for paper-account cash timing.",
        ],
    }
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()
    print(json.dumps(run(args.signal_path, args.output, args.start_year, args.end_year), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
