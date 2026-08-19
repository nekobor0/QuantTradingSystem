from __future__ import annotations

from pathlib import Path

import pandas as pd

import paper_trading.app as web
from paper_trading.market import DataStore


def test_effective_date_uses_latest_quote_not_future_calendar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pd.DataFrame(
        [{"ts_code": "AAA", "trade_date": "20260819", "open": 10.0, "close": 10.0}]
    ).to_parquet(tmp_path / "quotes.parquet", index=False)
    pd.DataFrame(
        [
            {"exchange": "SSE", "cal_date": "20260819", "is_open": 1},
            {"exchange": "SSE", "cal_date": "20260930", "is_open": 1},
        ]
    ).to_parquet(tmp_path / "calendar.parquet", index=False)
    monkeypatch.setattr(web, "store", DataStore(tmp_path))
    assert web._effective_date() == "2026-08-19"
