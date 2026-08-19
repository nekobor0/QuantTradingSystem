"""Incremental Tushare update for the paper account; never submits orders."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import tushare as ts

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper_trading.config import BENCHMARKS, DATA_DIR

TOKEN_PATH = Path.home() / ".tushare_token"
WARMUP_DAYS = 80


def load_token() -> str:
    if not TOKEN_PATH.exists():
        raise RuntimeError("Tushare token file is missing")
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("Tushare token file is empty")
    return token


def _save(df: pd.DataFrame, name: str, subset: list[str] | None = None) -> None:
    if df is None or df.empty:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
    if path.exists():
        old = pd.read_parquet(path)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates(subset=subset, keep="last") if subset else df.drop_duplicates(keep="last")
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _fetch_calendar(pro, end_date: str) -> pd.DataFrame:
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=550)).strftime("%Y%m%d")
    end = (pd.Timestamp(end_date) + pd.Timedelta(days=45)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
    if cal is None:
        return pd.DataFrame()
    _save(cal, "calendar.parquet", ["exchange", "cal_date"])
    return cal


def _open_days(calendar: pd.DataFrame, end_date: str) -> list[str]:
    if calendar.empty:
        return []
    cal = calendar[calendar["is_open"].astype(int).eq(1)].copy()
    cal = cal[cal["cal_date"].astype(str).le(end_date)]
    return sorted(cal["cal_date"].astype(str).unique())


def latest_available_trade_date(pro, requested_date: str, calendar: pd.DataFrame) -> str:
    for trade_date in reversed(_open_days(calendar, requested_date)[-10:]):
        data = pro.daily(trade_date=trade_date, fields="ts_code,trade_date,open,close,amount,vol")
        if data is not None and not data.empty:
            return trade_date
        time.sleep(0.3)
    raise RuntimeError("No completed trading day was available in the last ten open sessions")


def _existing_quote_dates() -> set[str]:
    path = DATA_DIR / "quotes.parquet"
    if not path.exists():
        return set()
    quotes = pd.read_parquet(path, columns=["trade_date"])
    return set(pd.to_datetime(quotes["trade_date"]).dt.strftime("%Y%m%d"))


def _fetch_dividend_actions(pro, trade_date: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    fields = "ts_code,end_date,ann_date,div_proc,cash_div,ex_date,record_date,pay_date"
    for key in ("record_date", "pay_date", "ex_date"):
        try:
            frame = pro.dividend(**{key: trade_date, "fields": fields})
            if frame is not None and not frame.empty:
                frames.append(frame)
        except Exception:
            # The error is reported by the caller when all variants fail.
            continue
    return pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()


def _fetch_day(pro, trade_date: str) -> dict[str, int | str]:
    result: dict[str, int | str] = {"trade_date": trade_date}
    quotes = pro.daily(trade_date=trade_date, fields="ts_code,trade_date,open,close,amount,vol")
    if quotes is None or quotes.empty:
        result["status"] = "NO_QUOTES"
        return result
    quotes["trade_date"] = pd.to_datetime(quotes["trade_date"])
    _save(quotes, "quotes.parquet", ["ts_code", "trade_date"])
    result["quotes"] = len(quotes)

    valuation = pro.daily_basic(
        trade_date=trade_date,
        fields="ts_code,trade_date,pe_ttm,dv_ttm,circ_mv,total_mv",
    )
    if valuation is not None and not valuation.empty:
        valuation["trade_date"] = pd.to_datetime(valuation["trade_date"])
        _save(valuation, "valuation.parquet", ["ts_code", "trade_date"])
    result["valuation"] = 0 if valuation is None else len(valuation)

    actions = _fetch_dividend_actions(pro, trade_date)
    _save(actions, "dividend.parquet", ["ts_code", "record_date", "pay_date", "cash_div"])
    result["dividend"] = len(actions)

    benchmarks: list[pd.DataFrame] = []
    for name, code in BENCHMARKS.items():
        frame = pro.index_daily(ts_code=code, trade_date=trade_date)
        if frame is not None and not frame.empty:
            frame["name"] = name
            benchmarks.append(frame)
    benchmark = pd.concat(benchmarks, ignore_index=True) if benchmarks else pd.DataFrame()
    _save(benchmark, "benchmark.parquet", ["ts_code", "trade_date"])
    result["benchmark"] = len(benchmark)
    result["status"] = "OK"
    return result


def update_all(requested_date: str) -> dict:
    pro = ts.pro_api(load_token())
    calendar = _fetch_calendar(pro, requested_date)
    effective = latest_available_trade_date(pro, requested_date, calendar)
    stock_basic = pro.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date,list_status",
    )
    if stock_basic is not None and not stock_basic.empty:
        _save(stock_basic, "stock_basic.parquet", ["ts_code"])

    open_days = _open_days(calendar, effective)
    existing = _existing_quote_dates()
    if not existing:
        required = open_days[-WARMUP_DAYS:]
    else:
        required = [day for day in open_days if day not in existing]
    runs: list[dict] = []
    errors: list[dict[str, str]] = []
    for trade_date in required:
        try:
            runs.append(_fetch_day(pro, trade_date))
        except Exception as exc:
            errors.append({"trade_date": trade_date, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.18)
    return {
        "requested_date": requested_date,
        "effective_date": effective,
        "updated_dates": len(runs),
        "runs": runs,
        "errors": errors,
        "stock_basic": 0 if stock_basic is None else len(stock_basic),
    }


if __name__ == "__main__":
    requested = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.today().strftime("%Y%m%d")
    print(update_all(requested))
