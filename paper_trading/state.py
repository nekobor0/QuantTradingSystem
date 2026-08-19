"""Atomic persistence and migration for the paper-account ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import DIV_CAPITAL, STATE_FILE, VOL_CAPITAL
from .models import (
    Book,
    CashEvent,
    DividendEntitlement,
    Fill,
    Lot,
    PaperState,
    PendingPlan,
)


def _book_from_dict(data: dict[str, Any], fallback_name: str, fallback_cash: float) -> Book:
    lots = {
        symbol: [Lot(**lot) for lot in raw_lots]
        for symbol, raw_lots in data.get("lots", {}).items()
    }
    return Book(
        name=data.get("name", fallback_name),
        cash=float(data.get("cash", fallback_cash)),
        lots=lots,
        model_weights={k: float(v) for k, v in data.get("model_weights", {}).items()},
        pending_plan=(PendingPlan(**data["pending_plan"]) if data.get("pending_plan") else None),
        fills=[Fill(**x) for x in data.get("fills", [])],
        cash_events=[CashEvent(**x) for x in data.get("cash_events", [])],
        entitlements=[DividendEntitlement(**x) for x in data.get("entitlements", [])],
        nav_history=list(data.get("nav_history", [])),
        last_prices={k: float(v) for k, v in data.get("last_prices", {}).items()},
        risk_position=float(data.get("risk_position", data.get("position", 1.0))),
    )


def _migrate_legacy(data: dict[str, Any]) -> PaperState:
    """Preserve old observations but mark synthetic legacy holdings as unverified."""
    start = data.get("start_date") or "UNKNOWN"
    if isinstance(start, str) and len(start) == 8 and start.isdigit():
        start = f"{start[:4]}-{start[4:6]}-{start[6:8]}"

    def convert(raw: dict[str, Any], name: str, fallback: float) -> Book:
        book = _book_from_dict(raw, name, fallback)
        if not book.lots:
            for symbol, shares in raw.get("holdings", {}).items():
                qty = int(shares)
                if qty > 0:
                    book.lots[symbol] = [Lot.new(qty, start, 0.0)]
        return book

    return PaperState(
        start_date=start,
        dividend_book=convert(data.get("dividend_book", {}), "dividend", DIV_CAPITAL),
        voltrend_book=convert(data.get("voltrend_book", {}), "voltrend", VOL_CAPITAL),
        run_history=list(data.get("run_history", [])),
        reconciliations=list(data.get("reconciliations", [])),
        alerts=list(data.get("alerts", [])),
        last_data_update=data.get("last_data_update"),
        last_scan=data.get("last_scan"),
        legacy_import=True,
    )


class StateRepository:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path

    def load(self) -> PaperState:
        if not self.path.exists():
            return PaperState()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if int(data.get("version", 1)) < 2:
            return _migrate_legacy(data)
        return PaperState(
            version=2,
            start_date=data.get("start_date", ""),
            dividend_book=_book_from_dict(data.get("dividend_book", {}), "dividend", DIV_CAPITAL),
            voltrend_book=_book_from_dict(data.get("voltrend_book", {}), "voltrend", VOL_CAPITAL),
            run_history=list(data.get("run_history", [])),
            reconciliations=list(data.get("reconciliations", [])),
            alerts=list(data.get("alerts", [])),
            last_data_update=data.get("last_data_update"),
            last_scan=data.get("last_scan"),
            legacy_import=bool(data.get("legacy_import", False)),
        )

    def save(self, state: PaperState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def reset(self) -> PaperState:
        state = PaperState()
        self.save(state)
        return state
