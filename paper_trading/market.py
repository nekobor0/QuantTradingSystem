"""Read-only market-data access, calendar logic, and PIT signal construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    DATA_DIR,
    FACTOR_WEIGHTS,
    MIN_ADV_CNY,
    MIN_LISTED_DAYS,
    TOP_N,
    YIELD_THRESHOLD,
)


def _as_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str), errors="coerce").dt.normalize()


class DataStore:
    def __init__(self, root: Path = DATA_DIR):
        self.root = root

    def read(self, name: str) -> pd.DataFrame:
        path = self.root / name
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def calendar(self) -> pd.DatetimeIndex:
        cal = self.read("calendar.parquet")
        if not cal.empty and {"cal_date", "is_open"}.issubset(cal.columns):
            dates = _as_date(cal.loc[cal["is_open"].astype(int).eq(1), "cal_date"])
            return pd.DatetimeIndex(sorted(dates.dropna().unique()))
        quotes = self.read("quotes.parquet")
        if quotes.empty:
            return pd.DatetimeIndex([])
        return pd.DatetimeIndex(sorted(_as_date(quotes["trade_date"]).dropna().unique()))

    def next_trading_day(self, trade_date: str) -> str | None:
        d = pd.Timestamp(trade_date).normalize()
        future = self.calendar()[self.calendar() > d]
        return future[0].strftime("%Y-%m-%d") if len(future) else None

    def is_last_trading_day_of_month(self, trade_date: str) -> bool:
        d = pd.Timestamp(trade_date).normalize()
        nxt = self.next_trading_day(trade_date)
        return bool(nxt and pd.Timestamp(nxt).month != d.month)

    def prices(self, trade_date: str, field: str) -> dict[str, float]:
        quotes = self.read("quotes.parquet")
        if quotes.empty or field not in quotes.columns:
            return {}
        dates = _as_date(quotes["trade_date"])
        day = quotes.loc[dates.eq(pd.Timestamp(trade_date).normalize()), ["ts_code", field]]
        day = day[day[field].notna() & day[field].gt(0)]
        return {str(k): float(v) for k, v in zip(day["ts_code"], day[field])}

    def up_limits(self, trade_date: str) -> dict[str, float]:
        limits = self.read("limits.parquet")
        if limits.empty or not {"trade_date", "ts_code", "up_limit"}.issubset(limits.columns):
            return {}
        dates = _as_date(limits["trade_date"])
        day = limits.loc[
            dates.eq(pd.Timestamp(trade_date).normalize()), ["ts_code", "up_limit"]
        ]
        day = day[day["up_limit"].notna() & day["up_limit"].gt(0)]
        return {str(k): float(v) for k, v in zip(day["ts_code"], day["up_limit"])}

    def corporate_actions(self) -> pd.DataFrame:
        return self.read("dividend.parquet")


def _eligible_frame(store: DataStore, trade_date: str) -> pd.DataFrame:
    d = pd.Timestamp(trade_date).normalize()
    quotes = store.read("quotes.parquet")
    val = store.read("valuation.parquet")
    basic = store.read("stock_basic.parquet")
    if quotes.empty or val.empty or basic.empty:
        return pd.DataFrame()
    qdates = _as_date(quotes["trade_date"])
    vdates = _as_date(val["trade_date"])
    q = quotes.loc[qdates.eq(d)].copy()
    v = val.loc[vdates.eq(d)].copy()
    b = basic.sort_values("ts_code").drop_duplicates("ts_code", keep="last").copy()
    frame = v.merge(q, on="ts_code", suffixes=("", "_quote")).merge(b, on="ts_code")
    frame["list_date"] = _as_date(frame["list_date"])
    frame["listed_days"] = (d - frame["list_date"]).dt.days
    name = frame.get("name", pd.Series("", index=frame.index)).fillna("").astype(str)
    market = frame.get("market", pd.Series("", index=frame.index)).fillna("").astype(str)
    frame["eligible"] = (
        frame["close"].gt(0)
        & frame["amount"].fillna(0).mul(1000).ge(MIN_ADV_CNY)
        & frame["listed_days"].ge(MIN_LISTED_DAYS)
        & frame.get("list_status", pd.Series("L", index=frame.index)).eq("L")
        & ~name.str.contains("ST|退", case=False, regex=True)
        & ~market.str.contains("北交所|BSE", case=False, regex=True)
        & ~frame["ts_code"].astype(str).str.endswith(".BJ")
    )
    return frame[frame["eligible"]].copy()


def dividend_weights(store: DataStore, trade_date: str) -> dict[str, float]:
    frame = _eligible_frame(store, trade_date)
    if frame.empty or "dv_ttm" not in frame:
        return {}
    frame["yield"] = frame["dv_ttm"].fillna(0.0) / 100.0
    selected = frame[frame["yield"].ge(YIELD_THRESHOLD)].nlargest(TOP_N, "yield")
    if selected.empty:
        return {}
    w = 1.0 / len(selected)
    return {str(symbol): w for symbol in selected["ts_code"]}


def balanced_weights(store: DataStore, trade_date: str) -> dict[str, float]:
    frame = _eligible_frame(store, trade_date)
    quotes = store.read("quotes.parquet")
    if frame.empty or quotes.empty:
        return {}
    quotes = quotes.copy()
    quotes["trade_date"] = _as_date(quotes["trade_date"])
    quotes = quotes[quotes["trade_date"].le(pd.Timestamp(trade_date))]
    quotes = quotes.sort_values(["ts_code", "trade_date"])
    quotes["ret"] = quotes.groupby("ts_code")["close"].pct_change()
    quotes["amihud"] = quotes["ret"].abs() / quotes["amount"].replace(0, np.nan)
    quotes["amihud20"] = quotes.groupby("ts_code")["amihud"].transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    latest = quotes.groupby("ts_code", as_index=False).tail(1)[["ts_code", "amihud20"]]
    frame = frame.merge(latest, on="ts_code", how="left")
    frame["ep"] = 1.0 / frame["pe_ttm"].where(frame["pe_ttm"].gt(0))
    frame["div_yield"] = frame["dv_ttm"].fillna(0.0) / 100.0
    frame = frame.dropna(subset=["ep", "amihud20"])
    if frame.empty:
        return {}
    for col in ("ep", "amihud20", "div_yield"):
        frame["r_" + col] = frame[col].rank(pct=True)
    frame["score"] = sum(
        FACTOR_WEIGHTS[key] * frame["r_" + source]
        for key, source in (("ep", "ep"), ("amihud", "amihud20"), ("div_yield", "div_yield"))
    )
    selected = frame.nlargest(TOP_N, "score")
    w = 1.0 / len(selected)
    return {str(symbol): w for symbol in selected["ts_code"]}

