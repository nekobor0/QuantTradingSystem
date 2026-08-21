"""Incremental Tushare update for the paper account; never submits orders."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

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


def _existing_dates(name: str) -> set[str]:
    path = DATA_DIR / name
    if not path.exists():
        return set()
    frame = pd.read_parquet(path, columns=["trade_date"])
    return set(pd.to_datetime(frame["trade_date"]).dt.strftime("%Y%m%d"))


def _existing_quote_dates() -> set[str]:
    return _existing_dates("quotes.parquet")


def _existing_limit_dates() -> set[str]:
    return _existing_dates("limits.parquet")


def _required_quote_dates(
    open_days: list[str], existing: set[str], existing_limits: set[str] | None = None
) -> list[str]:
    return [
        trade_date
        for trade_date in open_days[-WARMUP_DAYS:]
        if trade_date not in existing
        or (existing_limits is not None and trade_date not in existing_limits)
    ]


def _fetch_dividend_actions(pro, trade_date: str) -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    fields = "ts_code,end_date,ann_date,div_proc,cash_div,cash_div_tax,ex_date,record_date,pay_date"
    for key in ("record_date", "ex_date"):
        try:
            frame = pro.dividend(**{key: trade_date, "fields": fields})
            if frame is not None and not frame.empty:
                frames.append(frame)
        except Exception as exc:
            errors.append(f"{key}:{type(exc).__name__}:{exc}")
    return (pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()), errors


def _fetch_day(pro, trade_date: str) -> dict[str, Any]:
    result: dict[str, Any] = {"trade_date": trade_date}
    quotes = pro.daily(trade_date=trade_date, fields="ts_code,trade_date,open,close,amount,vol")
    if quotes is None or quotes.empty:
        result["status"] = "NO_QUOTES"
        return result
    quotes["trade_date"] = pd.to_datetime(quotes["trade_date"])
    _save(quotes, "quotes.parquet", ["ts_code", "trade_date"])
    result["quotes"] = len(quotes)

    limits = pro.stk_limit(
        trade_date=trade_date,
        fields="ts_code,trade_date,pre_close,up_limit,down_limit",
    )
    if limits is not None and not limits.empty:
        limits["trade_date"] = pd.to_datetime(limits["trade_date"])
        _save(limits, "limits.parquet", ["ts_code", "trade_date"])
    result["limits"] = 0 if limits is None else len(limits)

    valuation = pro.daily_basic(
        trade_date=trade_date,
        fields="ts_code,trade_date,pe_ttm,dv_ttm,circ_mv,total_mv",
    )
    if valuation is not None and not valuation.empty:
        valuation["trade_date"] = pd.to_datetime(valuation["trade_date"])
        _save(valuation, "valuation.parquet", ["ts_code", "trade_date"])
    result["valuation"] = 0 if valuation is None else len(valuation)

    actions, dividend_query_errors = _fetch_dividend_actions(pro, trade_date)
    result["dividend_query_errors"] = dividend_query_errors
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
    existing_limits = _existing_limit_dates()
    required = _required_quote_dates(open_days, existing, existing_limits)
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
