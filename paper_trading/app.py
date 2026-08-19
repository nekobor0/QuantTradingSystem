"""Local paper-account Web API. It contains no broker/order-submission adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper_trading.config import BASE_DIR, BENCHMARKS, DATA_DIR, PRINCIPAL
from paper_trading.data_update import update_all
from paper_trading.execution import book_nav, run_day
from paper_trading.market import DataStore
from paper_trading.models import Book
from paper_trading.monitoring import health_status, reconcile, record_alerts
from paper_trading.state import StateRepository
from paper_trading.strategies import scan

app = FastAPI(title="模拟仓 Web UI", version="2")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
repository = StateRepository()
store = DataStore()


class BookSnapshot(BaseModel):
    cash: float
    holdings: dict[str, int]


class ReconciliationRequest(BaseModel):
    trade_date: str
    dividend: BookSnapshot
    voltrend: BookSnapshot
    source: str = "manual_snapshot"
    cash_tolerance: float = 1.0


def _today() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def _effective_date() -> str:
    quotes = store.read("quotes.parquet")
    if not quotes.empty and "trade_date" in quotes:
        dates = pd.to_datetime(quotes["trade_date"].astype(str), errors="coerce").dropna()
        if not dates.empty:
            return dates.max().strftime("%Y-%m-%d")
    calendar = store.calendar()
    completed = calendar[calendar <= pd.Timestamp.today().normalize()]
    return completed[-1].strftime("%Y-%m-%d") if len(completed) else pd.Timestamp.today().strftime("%Y-%m-%d")


def _stock_names() -> dict[str, str]:
    basic = store.read("stock_basic.parquet")
    if basic.empty or not {"ts_code", "name"}.issubset(basic.columns):
        return {}
    latest = basic.sort_values("ts_code").drop_duplicates("ts_code", keep="last")
    return {str(code): str(name) for code, name in zip(latest["ts_code"], latest["name"])}


def _holding_rows(
    book: Book,
    prices: dict[str, float],
    names: dict[str, str],
    nav: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, shares in book.holdings.items():
        lots = book.lots.get(symbol, [])
        price = prices.get(symbol) or book.last_prices.get(symbol) or 0.0
        total_cost = sum(lot.shares * lot.unit_cost for lot in lots)
        market_value = shares * price
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "shares": shares,
                "lots": len(lots),
                "first_acquired_date": min((lot.acquired_date for lot in lots), default=""),
                "average_cost": round(total_cost / shares, 4) if shares else 0.0,
                "close": round(price, 4),
                "market_value": round(market_value, 2),
                "nav_weight": round(market_value / nav, 8) if nav else 0.0,
            }
        )
    return sorted(rows, key=lambda row: row["market_value"], reverse=True)


def _update_summary(result: dict[str, Any]) -> dict[str, Any]:
    runs = result.get("runs", [])
    dividend_query_errors = [
        {"trade_date": row.get("trade_date"), "error": error}
        for row in runs
        for error in row.get("dividend_query_errors", [])
    ]
    return {
        "requested_date": result.get("requested_date"),
        "effective_date": result.get("effective_date"),
        "updated_dates": result.get("updated_dates", 0),
        "errors": result.get("errors", []),
        "dividend_query_errors": dividend_query_errors,
        "stock_basic": result.get("stock_basic", 0),
        "quotes": sum(int(row.get("quotes", 0)) for row in runs),
        "valuation": sum(int(row.get("valuation", 0)) for row in runs),
        "dividend": sum(int(row.get("dividend", 0)) for row in runs),
        "benchmark": sum(int(row.get("benchmark", 0)) for row in runs),
        "status": "PASS" if not result.get("errors") and not dividend_query_errors else "PARTIAL",
    }


def _update_failure_summary(requested_date: str, exc: Exception) -> dict[str, Any]:
    return {
        "requested_date": requested_date,
        "effective_date": _effective_date(),
        "updated_dates": 0,
        "errors": [{"trade_date": requested_date, "error": f"{type(exc).__name__}: {exc}"}],
        "dividend_query_errors": [],
        "stock_basic": 0,
        "quotes": 0,
        "valuation": 0,
        "dividend": 0,
        "benchmark": 0,
        "status": "FAIL",
    }


def _model_dump(value: BaseModel) -> dict[str, Any]:
    method = getattr(value, "model_dump", None)
    return method() if method else value.dict()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/state")
def api_state():
    state = repository.load()
    trade_date = _effective_date()
    prices = store.prices(trade_date, "close")
    names = _stock_names()
    dividend_nav, dividend_warnings = book_nav(state.dividend_book, prices)
    voltrend_nav, voltrend_warnings = book_nav(state.voltrend_book, prices)
    return {
        "version": state.version,
        "legacy_import": state.legacy_import,
        "start_date": state.start_date,
        "effective_date": trade_date,
        "principal": PRINCIPAL,
        "last_data_update": state.last_data_update,
        "last_scan": state.last_scan,
        "latest_run": state.run_history[-1] if state.run_history else None,
        "dividend": {
            "cash": round(state.dividend_book.cash, 2),
            "nav": round(dividend_nav, 2),
            "holdings": state.dividend_book.holdings,
            "holding_rows": _holding_rows(state.dividend_book, prices, names, dividend_nav),
            "pending_plan": state.dividend_book.pending_plan,
        },
        "voltrend": {
            "cash": round(state.voltrend_book.cash, 2),
            "nav": round(voltrend_nav, 2),
            "position": state.voltrend_book.risk_position,
            "holdings": state.voltrend_book.holdings,
            "holding_rows": _holding_rows(state.voltrend_book, prices, names, voltrend_nav),
            "pending_plan": state.voltrend_book.pending_plan,
        },
        "total_nav": round(dividend_nav + voltrend_nav, 2),
        "warnings": dividend_warnings + voltrend_warnings,
        "alerts": state.alerts[-100:],
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


@app.get("/api/p2/status")
def api_p2_status():
    state = repository.load()
    return health_status(state, store, _effective_date())


@app.post("/api/p2/check")
def api_p2_check():
    state = repository.load()
    status = health_status(state, store, _effective_date())
    record_alerts(state, status)
    repository.save(state)
    return status


@app.post("/api/p2/reconcile")
def api_p2_reconcile(payload: ReconciliationRequest):
    state = repository.load()
    record = reconcile(
        state,
        payload.trade_date,
        _model_dump(payload.dividend),
        _model_dump(payload.voltrend),
        payload.source,
        payload.cash_tolerance,
    )
    status = health_status(state, store, payload.trade_date)
    record_alerts(state, status)
    repository.save(state)
    return {"reconciliation": record, "p2": status}


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
    requested = trade_date or _today()
    state = repository.load()
    try:
        result = update_all(requested)
        state.last_data_update = _update_summary(result)
    except Exception as exc:
        state.last_data_update = _update_failure_summary(requested, exc)
        repository.save(state)
        raise HTTPException(status_code=503, detail=state.last_data_update) from exc
    repository.save(state)
    return result


@app.post("/api/scan")
def api_scan(trade_date: str | None = None):
    state = repository.load()
    result = scan(state, store, trade_date or _effective_date())
    state.last_scan = result
    repository.save(state)
    return result


@app.post("/api/run_daily")
def api_run_daily(trade_date: str | None = None, update_data: bool = True):
    update = update_all(trade_date or _today()) if update_data else None
    effective = update["effective_date"] if update else (trade_date or _effective_date())
    effective = pd.Timestamp(effective).strftime("%Y-%m-%d")
    state = repository.load()
    if update:
        state.last_data_update = _update_summary(update)
    result = run_day(state, store, effective)
    if result.get("status") == "COMPLETE":
        latest_scan = scan(state, store, effective)
        state.last_scan = latest_scan
        result["scan"] = latest_scan
        p2 = health_status(state, store, effective)
        record_alerts(state, p2)
        result["p2"] = p2
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
