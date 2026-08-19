"""模拟仓 Web UI 后端（FastAPI）。"""
from __future__ import annotations
import pandas as pd

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import BASE_DIR, DATA_DIR, PRINCIPAL, BENCHMARKS
from state import State, book_nav
from data_update import update_all, latest_quote_date
import strategies as st

app = FastAPI(title="模拟仓 Web UI")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _today() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def _eff() -> str:
    return latest_quote_date() or _today()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/state")
def api_state():
    s = State.load()
    td = _eff()
    q = st.load_prices(td) or {}
    div_nav = book_nav(s.dividend_book, q)
    vol_nav = book_nav(s.voltrend_book, q)
    return {
        "start_date": s.start_date or "",
        "effective_date": td,
        "principal": PRINCIPAL,
        "dividend": {"cash": round(s.dividend_book.cash, 2), "nav": round(div_nav, 2),
                     "holdings": s.dividend_book.holdings},
        "voltrend": {"cash": round(s.voltrend_book.cash, 2), "nav": round(vol_nav, 2),
                     "position": s.voltrend_book.position, "holdings": s.voltrend_book.holdings},
        "total_nav": round(div_nav + vol_nav, 2),
    }


@app.get("/api/nav")
def api_nav():
    s = State.load()
    dh = s.dividend_book.nav_history
    vh = s.voltrend_book.nav_history
    dates = [h["date"] for h in dh] if dh else []
    div = [h["nav"] for h in dh] if dh else []
    volt = [h["nav"] for h in vh] if vh else []
    comb = [d + v for d, v in zip(div, volt)] if len(div) == len(volt) else []
    return {"dates": dates, "dividend": div, "voltrend": volt, "combined": comb}


@app.get("/api/benchmark")
def api_benchmark():
    p = DATA_DIR / "benchmark.parquet"
    if not p.exists():
        return {"dates": [], "series": {}}
    b = pd.read_parquet(p)
    b["trade_date"] = pd.to_datetime(b["trade_date"].astype(str))
    b = b.sort_values("trade_date")
    out = {"dates": [d.strftime("%Y-%m-%d") for d in b["trade_date"].unique()], "series": {}}
    for name in BENCHMARKS:
        sub = b[b["name"] == name]
        out["series"][name] = list(sub["close"])
    return out


@app.post("/api/update_data")
def api_update_data(trade_date: str | None = None):
    td = trade_date or _today()
    return update_all(td)


@app.post("/api/scan")
def api_scan(trade_date: str | None = None):
    td = trade_date or _eff()
    s = State.load()
    return st.scan(s, td)


@app.post("/api/run_daily")
def api_run_daily(trade_date: str | None = None):
    td = trade_date or _today()
    upd = update_all(td)
    eff = upd.get("effective_date", td)
    s = State.load()
    r = st.execute_daily(s, eff)
    if "error" not in r:
        if not s.start_date:
            s.start_date = eff
        s.save()
    r["data_update"] = upd
    return r


@app.post("/api/reset")
def api_reset():
    State.reset()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
