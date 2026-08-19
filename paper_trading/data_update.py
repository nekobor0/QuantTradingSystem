"""每日盘后数据更新：行情/估值/分红/指数，落盘到 data/ 目录。

盘中执行时自动回退到最近一个已收盘交易日；首次运行自动回填约 70 个交易日
行情与估值，用于计算波动率分仓的 amihud20（60 日窗口）。
"""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import tushare as ts

from config import DATA_DIR, BENCHMARKS

TOKEN_PATH = Path.home() / ".tushare_token"
WARMUP_DAYS = 70  # amihud20 需要 60 日窗口，预热 70 个交易日


def load_token() -> str:
    return TOKEN_PATH.read_text().strip()


def _save(df, name: str, append: bool = True) -> None:
    if df is None or len(df) == 0:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = DATA_DIR / name
    if append and p.exists():
        old = pd.read_parquet(p)
        if not old.empty:
            df = pd.concat([old, df], ignore_index=True).drop_duplicates()
    df.to_parquet(p, index=False)


def _trading_days(pro, end_date: str, n: int) -> list:
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=n * 2 + 20)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end_date, is_open="1")
    days = cal["cal_date"].astype(str).sort_values(ascending=False).tolist()
    return days[:n]


def latest_available_trade_date(pro, end_date: str, lookback: int = 10) -> str:
    """从 end_date 向前找最近一个 pro.daily 有数据的交易日。"""
    for d in _trading_days(pro, end_date, lookback):
        df = pro.daily(trade_date=d, fields="ts_code,trade_date,open,close,amount,vol")
        if df is not None and len(df):
            return d
        time.sleep(0.4)
    return end_date


def latest_quote_date() -> str:
    """读 data/quotes.parquet，返回最近一个有行情的交易日（YYYYMMDD）。"""
    p = DATA_DIR / "quotes.parquet"
    if not p.exists():
        return ""
    q = pd.read_parquet(p)
    if q.empty:
        return ""
    return pd.Timestamp(q["trade_date"].max()).strftime("%Y%m%d")


def _warmup(pro, end_date: str) -> int:
    """首次运行：回填 end_date 之前约 WARMUP_DAYS 个交易日的行情(daily)，
    用于计算 amihud20(60 日窗口)。估值仅需当日，由 update_valuation 单独拉取。"""
    days = _trading_days(pro, end_date, WARMUP_DAYS + 1)[1:]  # 去掉 end_date 本身
    qs = []
    for d in days:
        try:
            q = pro.daily(trade_date=d, fields="ts_code,trade_date,open,close,amount,vol")
            if q is not None and len(q):
                q["trade_date"] = pd.to_datetime(q["trade_date"])
                qs.append(q)
        except Exception:
            pass
        time.sleep(0.2)
    if qs:
        _save(pd.concat(qs, ignore_index=True), "quotes.parquet")
    return len(days)


def update_quotes(pro, trade_date: str) -> pd.DataFrame:
    df = pro.daily(trade_date=trade_date, fields="ts_code,trade_date,open,close,amount,vol")
    if df is not None and len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        _save(df, "quotes.parquet")
    return df if df is not None and len(df) else pd.DataFrame()


def update_valuation(pro, trade_date: str) -> pd.DataFrame:
    df = pro.daily_basic(trade_date=trade_date, fields="ts_code,trade_date,pe_ttm,dv_ttm,circ_mv,total_mv")
    if df is not None and len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        _save(df, "valuation.parquet")
    return df if df is not None and len(df) else pd.DataFrame()


def update_dividend(pro, trade_date: str) -> pd.DataFrame:
    df = pro.dividend(ex_date=trade_date, fields="ts_code,end_date,cash_div,ex_date,record_date,pay_date,div_proc")
    if df is not None and len(df):
        df = df[df["div_proc"].astype(str).str.contains("实施", na=False)]
        _save(df, "dividend.parquet")
    return df if df is not None and len(df) else pd.DataFrame()


def update_benchmark(pro, trade_date: str) -> pd.DataFrame:
    frames = []
    for name, code in BENCHMARKS.items():
        df = pro.index_daily(ts_code=code, trade_date=trade_date)
        if df is not None and len(df):
            df["name"] = name
            frames.append(df)
    if frames:
        out = pd.concat(frames, ignore_index=True)
        _save(out, "benchmark.parquet")
        return out
    return pd.DataFrame()


def update_all(trade_date: str) -> dict:
    """执行全部更新，返回各表行数与生效交易日。"""
    pro = ts.pro_api(load_token())
    eff = latest_available_trade_date(pro, trade_date)
    result = {"requested_date": trade_date, "effective_date": eff}
    qp = DATA_DIR / "quotes.parquet"
    first_run = (not qp.exists()) or pd.read_parquet(qp).empty
    if first_run:
        result["warmup_days"] = _warmup(pro, eff)
    for fn, key in [(update_quotes, "quotes"), (update_valuation, "valuation"),
                    (update_dividend, "dividend"), (update_benchmark, "benchmark")]:
        try:
            result[key] = len(fn(pro, eff))
        except Exception as e:  # noqa: BLE001
            result[key] = f"ERR: {e}"
    return result


if __name__ == "__main__":
    import sys
    td = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.today().strftime("%Y%m%d")
    print(update_all(td))
