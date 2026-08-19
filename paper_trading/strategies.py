"""两个分仓的每日执行逻辑：直接本地执行（建仓/调仓/复投/仓位调整）。"""
from __future__ import annotations
import numpy as np
import pandas as pd

from config import (DATA_DIR, YIELD_THRESHOLD, TOP_N, FACTOR_WEIGHTS,
                    TARGET_VOL, VOL_WINDOW, MA_N, STAMP_DUTY, COMMISSION)
from state import State, Book, book_nav


def _load(name: str) -> pd.DataFrame:
    p = DATA_DIR / name
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _td(trade_date: str) -> str:
    return trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:8]


def load_prices(trade_date: str) -> dict:
    q = _load("quotes.parquet")
    if q.empty:
        return {}
    q = q[q["trade_date"].astype(str).str[:10] == _td(trade_date)]
    return dict(zip(q["ts_code"], q["close"]))


def compute_total_yield(trade_date: str) -> pd.DataFrame:
    val = _load("valuation.parquet")
    if val.empty:
        return pd.DataFrame(columns=["ts_code", "total_yield"])
    val = val[val["trade_date"].astype(str).str[:10] == _td(trade_date)]
    val = val[val["dv_ttm"].notna()]
    val["total_yield"] = val["dv_ttm"] / 100.0
    return val[["ts_code", "total_yield"]]


def compute_balanced_factors(trade_date: str) -> pd.DataFrame:
    val = _load("valuation.parquet")
    quotes = _load("quotes.parquet")
    if val.empty:
        return pd.DataFrame(columns=["ts_code", "score"])
    v = val[val["trade_date"].astype(str).str[:10] == _td(trade_date)].copy()
    if v.empty:
        return pd.DataFrame(columns=["ts_code", "score"])
    v["ep"] = 1.0 / v["pe_ttm"].where(v["pe_ttm"] > 0)
    v["div_yield"] = v["dv_ttm"].fillna(0.0) / 100.0
    q = quotes.copy()
    q["trade_date"] = pd.to_datetime(q["trade_date"].astype(str))
    q = q.sort_values(["ts_code", "trade_date"])
    q["ret"] = q.groupby("ts_code")["close"].pct_change()
    q["amihud"] = q["ret"].abs() / q["amount"].replace(0, np.nan)
    q["amihud20"] = q.groupby("ts_code")["amihud"].transform(lambda s: s.rolling(VOL_WINDOW, min_periods=10).mean())
    q = q[q["trade_date"].astype(str).str[:10] == _td(trade_date)][["ts_code", "amihud20"]]
    v = v.merge(q, on="ts_code", how="left")
    v["amihud20"] = v["amihud20"].fillna(0.0)
    for c in ["ep", "amihud20", "div_yield"]:
        v["r_" + c] = v[c].rank(pct=True)
    v["score"] = (FACTOR_WEIGHTS["ep"] * v["r_ep"] + FACTOR_WEIGHTS["amihud"] * v["r_amihud20"]
                  + FACTOR_WEIGHTS["div_yield"] * v["r_div_yield"])
    return v[["ts_code", "score"]]


def _is_month_end(trade_date: str) -> bool:
    return pd.Timestamp(_td(trade_date)).is_month_end


def _buy(book, ts_code, price, amount, reason, trades):
    if price <= 0 or amount <= 0:
        return
    shares = int(amount / price / 100) * 100
    if shares <= 0:
        return
    cost = shares * price * (1 + COMMISSION)
    if cost > book.cash + 1e-6:
        shares = int(book.cash / price / (1 + COMMISSION) / 100) * 100
        cost = shares * price * (1 + COMMISSION) if shares > 0 else 0
    if shares <= 0:
        return
    book.holdings[ts_code] = book.holdings.get(ts_code, 0) + shares
    book.cash -= cost
    trades.append({"action": "buy", "ts_code": ts_code, "shares": shares, "amount": round(cost, 2), "reason": reason})


def _sell(book, ts_code, price, trades):
    shares = book.holdings.get(ts_code, 0)
    if shares <= 0:
        return
    cash = shares * price * (1 - COMMISSION - STAMP_DUTY)
    book.holdings.pop(ts_code, None)
    book.cash += cash
    trades.append({"action": "sell", "ts_code": ts_code, "shares": shares, "amount": round(cash, 2), "reason": "调出"})


def execute_dividend(book, trade_date, prices):
    trades = []
    is_first = not book.holdings
    if is_first or _is_month_end(trade_date):
        y = compute_total_yield(trade_date)
        y = y[y["total_yield"] >= YIELD_THRESHOLD].sort_values("total_yield", ascending=False)
        y = y[y["ts_code"].isin(prices)]
        target = y.head(TOP_N)["ts_code"].tolist()
        for c in list(book.holdings):
            if c not in target:
                _sell(book, c, prices.get(c, 0), trades)
        n = len(target)
        if n:
            per = book.cash / n
            for c in target:
                _buy(book, c, prices.get(c, 0), per, "建仓/调入 top-100", trades)
    div = _load("dividend.parquet")
    if not div.empty:
        div = div[div["ex_date"].astype(str).str[:10] == _td(trade_date)]
        for _, e in div.iterrows():
            c = e["ts_code"]
            if c in book.holdings and e.get("cash_div") and e["cash_div"] > 0:
                cash = float(e["cash_div"]) * book.holdings[c]
                _buy(book, c, prices.get(c, 0), cash, "除权复投", trades)
    return trades


def execute_voltrend(book, trade_date, prices, nav):
    trades = []
    rets = [h["ret"] for h in book.nav_history]
    vol = float(np.std(rets[-VOL_WINDOW:])) * np.sqrt(252) if len(rets) >= 10 else 0.0
    pos_vol = min(1.0, TARGET_VOL / vol) if vol > 0 else 1.0
    navs = [h["nav"] for h in book.nav_history]
    ma = float(np.mean(navs[-MA_N:])) if len(navs) >= MA_N else nav
    pos_trend = 1.0 if nav >= ma else 0.0
    target_pos = pos_vol * pos_trend
    book.position = round(target_pos, 4)
    is_first = not book.holdings
    if is_first or _is_month_end(trade_date):
        f = compute_balanced_factors(trade_date)
        f = f[f["ts_code"].isin(prices)]
        target = f.sort_values("score", ascending=False).head(TOP_N)["ts_code"].tolist()
        for c in list(book.holdings):
            if c not in target:
                _sell(book, c, prices.get(c, 0), trades)
        n = len(target)
        if n:
            per = (book.cash * target_pos) / n
            for c in target:
                _buy(book, c, prices.get(c, 0), per, "建仓/调入 top-100", trades)
    return trades, target_pos


def execute_daily(state, trade_date):
    prices = load_prices(trade_date)
    if not prices:
        return {"date": trade_date, "error": "无当日行情，请先更新数据（盘中请用最近已收盘交易日，系统会自动回退）"}
    td = _td(trade_date)
    if (state.dividend_book.nav_history and state.dividend_book.nav_history[-1]["date"] == td
            and state.voltrend_book.nav_history and state.voltrend_book.nav_history[-1]["date"] == td):
        div_nav = book_nav(state.dividend_book, prices)
        vol_nav = book_nav(state.voltrend_book, prices)
        return {
            "date": trade_date,
            "already_executed": True,
            "dividend": {"nav": round(div_nav, 2), "trades": []},
            "voltrend": {"nav": round(vol_nav, 2), "position": state.voltrend_book.position, "trades": []},
            "total_nav": round(div_nav + vol_nav, 2),
        }
    dt = execute_dividend(state.dividend_book, trade_date, prices)
    div_nav = book_nav(state.dividend_book, prices)
    vt, pos = execute_voltrend(state.voltrend_book, trade_date, prices, book_nav(state.voltrend_book, prices))
    vol_nav = book_nav(state.voltrend_book, prices)
    _record(state, trade_date, div_nav, vol_nav)
    return {
        "date": trade_date,
        "dividend": {"nav": round(div_nav, 2), "trades": dt},
        "voltrend": {"nav": round(vol_nav, 2), "position": pos, "trades": vt},
        "total_nav": round(div_nav + vol_nav, 2),
    }


def scan(state, trade_date):
    prices = load_prices(trade_date)
    y = compute_total_yield(trade_date)
    d_target = (y[y["total_yield"] >= YIELD_THRESHOLD].sort_values("total_yield", ascending=False)
                .head(TOP_N)["ts_code"].tolist() if not y.empty else [])
    f = compute_balanced_factors(trade_date)
    v_target = (f.sort_values("score", ascending=False).head(TOP_N)["ts_code"].tolist()
                if not f.empty else [])
    return {
        "date": trade_date,
        "is_month_end": _is_month_end(trade_date),
        "has_prices": bool(prices),
        "has_data": bool(not y.empty or not f.empty),
        "dividend_target_count": len(d_target),
        "voltrend_target_count": len(v_target),
        "dividend_target": d_target[:20],
        "voltrend_target": v_target[:20],
        "current_dividend_holdings": list(state.dividend_book.holdings),
        "current_voltrend_holdings": list(state.voltrend_book.holdings),
    }


def _record(state, trade_date, div_nav, vol_nav):
    td = _td(trade_date)

    def _append(book, nav):
        if book.nav_history and book.nav_history[-1]["date"] == td:
            book.nav_history[-1]["nav"] = round(nav, 2)
            return
        prev = book.nav_history[-1]["nav"] if book.nav_history else book.cash
        ret = (nav / prev - 1.0) if prev else 0.0
        book.nav_history.append({"date": td, "nav": round(nav, 2), "ret": round(ret, 6)})

    _append(state.dividend_book, div_nav)
    _append(state.voltrend_book, vol_nav)
