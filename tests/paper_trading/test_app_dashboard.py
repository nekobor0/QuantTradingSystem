from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

import paper_trading.app as web
import paper_trading.strategies as strategies
from paper_trading.config import DIV_CAPITAL, TOP_N, VOL_CAPITAL
from paper_trading.data_update import WARMUP_DAYS, _fetch_dividend_actions, _required_quote_dates
from paper_trading.market import DataStore
from paper_trading.models import Lot, PaperState
from paper_trading.state import StateRepository


def test_best_strategy_is_the_new_empty_account_default() -> None:
    state = PaperState()
    assert TOP_N == 50
    assert DIV_CAPITAL == 250_000.0
    assert VOL_CAPITAL == 750_000.0
    assert state.dividend_book.cash == DIV_CAPITAL
    assert state.voltrend_book.cash == VOL_CAPITAL


def test_dashboard_exposes_ordered_pipeline_p2_signals_and_close_holdings() -> None:
    html = (Path(web.BASE_DIR) / "templates" / "index.html").read_text(encoding="utf-8")
    for number in range(1, 6):
        assert f'<span class="step-no">{number}</span>' in html
    assert "数据更新结果" in html
    assert "当天扫描信号" in html
    assert "有效交易日收盘持仓" in html
    assert "P2 独立影子验证" in html
    assert "禁止用内部账本自动回填" in html


def test_p2_reconciliation_endpoint_accepts_an_external_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web, "repository", StateRepository(tmp_path / "state.json"))
    monkeypatch.setattr(web, "store", DataStore(tmp_path))
    client = TestClient(web.app)
    response = client.post(
        "/api/p2/reconcile",
        json={
            "trade_date": "2026-08-19",
            "source": "test_external_snapshot",
            "dividend": {"cash": 250_000.0, "holdings": {}},
            "voltrend": {"cash": 750_000.0, "holdings": {}},
        },
    )
    assert response.status_code == 200
    assert response.json()["reconciliation"]["status"] == "PASS"
    assert response.json()["p2"]["live_order_submission"] is False


def test_scan_returns_full_buy_and_sell_constituent_changes(monkeypatch) -> None:
    class StubStore:
        def read(self, name: str) -> pd.DataFrame:
            assert name == "stock_basic.parquet"
            return pd.DataFrame(
                {"ts_code": ["AAA", "BBB", "CCC"], "name": ["甲", "乙", "丙"]}
            )

        def is_last_trading_day_of_month(self, trade_date: str) -> bool:
            return True

        def next_trading_day(self, trade_date: str) -> str:
            return "2026-09-01"

    monkeypatch.setattr(strategies, "dividend_weights", lambda store, date: {"BBB": 0.5, "CCC": 0.5})
    monkeypatch.setattr(strategies, "balanced_weights", lambda store, date: {"CCC": 1.0})
    state = PaperState()
    state.dividend_book.lots = {
        "AAA": [Lot.new(100, "2026-01-01", 10.0)],
        "BBB": [Lot.new(100, "2026-01-01", 10.0)],
    }
    result = strategies.scan(state, StubStore(), "2026-08-31")
    assert [row["symbol"] for row in result["dividend_changes"]["buy"]] == ["CCC"]
    assert [row["symbol"] for row in result["dividend_changes"]["sell"]] == ["AAA"]
    assert result["signal_status"] == "REBALANCE_DUE"


def test_dividend_daily_query_uses_supported_dates_and_surfaces_partial_errors() -> None:
    class Pro:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def dividend(self, **kwargs):
            self.calls.append(kwargs)
            if "record_date" in kwargs:
                return pd.DataFrame(
                    [{"ts_code": "000001.SZ", "cash_div": 0.7, "cash_div_tax": 0.719}]
                )
            raise RuntimeError("temporary endpoint error")

    pro = Pro()
    frame, errors = _fetch_dividend_actions(pro, "20260819")
    assert [{key for key in call if key != "fields"} for call in pro.calls] == [
        {"record_date"},
        {"ex_date"},
    ]
    assert "cash_div_tax" in pro.calls[0]["fields"]
    assert frame.iloc[0]["cash_div_tax"] == 0.719
    assert errors and errors[0].startswith("ex_date:RuntimeError")


def test_incremental_update_never_backfills_beyond_the_warmup_window() -> None:
    open_days = [f"D{index:03d}" for index in range(WARMUP_DAYS + 50)]
    existing = {open_days[-1]}
    required = _required_quote_dates(open_days, existing)
    assert required == open_days[-WARMUP_DAYS:-1]
