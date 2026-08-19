"""Deterministically rebuild a paper-only shadow ledger across open trading days."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import (
    ALLOW_LIVE_TRADING,
    ENABLE_ORDER_SUBMISSION,
    STATE_FILE,
    TRADING_MODE,
)
from .execution import run_day
from .market import DataStore
from .models import PaperState
from .monitoring import health_status, record_alerts
from .state import StateRepository
from .strategies import scan


def replay(
    store: DataStore,
    repository: StateRepository,
    start: str,
    end: str,
    confirm_reset: bool,
) -> dict:
    if not confirm_reset:
        raise ValueError("--confirm-reset is required")
    if TRADING_MODE != "paper" or ALLOW_LIVE_TRADING or ENABLE_ORDER_SUBMISSION:
        raise RuntimeError("replay is restricted to paper-only mode")
    start_date = pd.Timestamp(start).normalize()
    end_date = pd.Timestamp(end).normalize()
    open_days = store.calendar()
    selected = open_days[(open_days >= start_date) & (open_days <= end_date)]
    if len(selected) == 0 or selected[0] != start_date or selected[-1] != end_date:
        raise ValueError("start and end must be available open trading days")

    previous = repository.load()
    state = PaperState(last_data_update=previous.last_data_update)
    runs: list[dict] = []
    for value in selected:
        trade_date = pd.Timestamp(value).strftime("%Y-%m-%d")
        result = run_day(state, store, trade_date)
        if result.get("status") != "COMPLETE":
            raise RuntimeError(f"replay blocked on {trade_date}: {result}")
        state.last_scan = scan(state, store, trade_date)
        p2 = health_status(state, store, trade_date)
        record_alerts(state, p2)
        repository.save(state)
        runs.append(result)

    return {
        "mode": "PAPER_REPLAY",
        "start": start_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d"),
        "open_trading_days": len(selected),
        "complete_runs": len(runs),
        "dividend_fills": len(state.dividend_book.fills),
        "voltrend_fills": len(state.voltrend_book.fills),
        "latest_scan": state.last_scan,
        "latest_run": state.run_history[-1] if state.run_history else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--state-file", type=Path, default=STATE_FILE)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--confirm-reset", action="store_true")
    args = parser.parse_args()
    store = DataStore(args.data_root) if args.data_root else DataStore()
    result = replay(
        store,
        StateRepository(args.state_file),
        args.start,
        args.end,
        args.confirm_reset,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
