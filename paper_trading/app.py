"""Local paper-account Web API. It contains no broker/order-submission adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper_trading.config import BASE_DIR, BENCHMARKS, DATA_DIR, PRINCIPAL
from paper_trading.data_update import update_all
from paper_trading.execution import book_nav, run_day
from paper_trading.market import DataStore
from paper_trading.state import StateRepository
from paper_trading.strategies import scan

app = FastAPI(title="模拟仓 Web UI", version="2")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
repository = StateRepository()
store = DataStore()


def _today() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def _effective_date() -> str:
    calendar = store.calendar()
    return calendar[-1].strftime("%Y-%m-%d") if len(calendar) else pd.Timestamp.today().strftime("%Y-%m-%d")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/state")
def api_state():
    state = repository.load()
    trade_date = _effective_date()
    prices = store.prices(trade_date, "close")
    dividend_nav, dividend_warnings = book_nav(state.dividend_book, prices)
    voltrend_nav, voltrend_warnings = book_nav(state.voltrend_book, prices)
    return {
        "version": state.version,
        "legacy_import": state.legacy_import,
        "start_date": state.start_date,
        "effective_date": trade_date,
        "principal": PRINCIPAL,
        "dividend": {
            "cash": round(state.dividend_book.cash, 2),
            "nav": round(dividend_nav, 2),
            "holdings": state.dividend_book.holdings,
            "pending_plan": state.dividend_book.pending_plan,
        },
        "voltrend": {
            "cash": round(state.voltrend_book.cash, 2),
            "nav": round(voltrend_nav, 2),
            "position": state.voltrend_book.risk_position,
            "holdings": state.voltrend_book.holdings,
            "pending_plan": state.voltrend_book.pending_plan,
        },
        "total_nav": round(dividend_nav + voltrend_nav, 2),
        "warnings": dividend_warnings + voltrend_warnings,
    }


@app.get("/api/nav")
def api_nav():
    state = repository.load()
    dividend = state.dividend_book.nav_history
    voltrend = state.voltrend_book.nav_history
    dates = [row["date"] for row in dividend]
    return {
        "dates": dates,
        "dividend": [row["nav"] for row in dividend],
        "voltrend": [row["nav"] for row in voltrend],
        "combined": [a["nav"] + b["nav"] for a, b in zip(dividend, voltrend)],
    }


@app.get("/api/audit")
def api_audit():
    state = repository.load()
    return {
        "runs": state.run_history[-60:],
        "dividend_fills": [fill.__dict__ for fill in state.dividend_book.fills[-500:]],
        "voltrend_fills": [fill.__dict__ for fill in state.voltrend_book.fills[-500:]],
        "dividend_cash_events": [event.__dict__ for event in state.dividend_book.cash_events[-200:]],
        "voltrend_cash_events": [event.__dict__ for event in state.voltrend_book.cash_events[-200:]],
    }


@app.get("/api/benchmark")
def api_benchmark():
    path = DATA_DIR / "benchmark.parquet"
    if not path.exists():
        return {"dates": [], "series": {}}
    frame = pd.read_parquet(path)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str))
    frame = frame.sort_values("trade_date")
    dates = sorted(frame["trade_date"].unique())
    return {
        "dates": [pd.Timestamp(value).strftime("%Y-%m-%d") for value in dates],
        "series": {
            name: frame[frame["name"].eq(name)].sort_values("trade_date")["close"].tolist()
            for name in BENCHMARKS
        },
    }


@app.post("/api/update_data")
def api_update_data(trade_date: str | None = None):
    return update_all(trade_date or _today())


@app.post("/api/scan")
def api_scan(trade_date: str | None = None):
    state = repository.load()
    return scan(state, store, trade_date or _effective_date())


@app.post("/api/run_daily")
def api_run_daily(trade_date: str | None = None, update_data: bool = True):
    update = update_all(trade_date or _today()) if update_data else None
    effective = update["effective_date"] if update else (trade_date or _effective_date())
    effective = pd.Timestamp(effective).strftime("%Y-%m-%d")
    state = repository.load()
    result = run_day(state, store, effective)
    if result.get("status") == "COMPLETE":
        repository.save(state)
    result["data_update"] = update
    return result


@app.post("/api/reset")
def api_reset():
    repository.reset()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
