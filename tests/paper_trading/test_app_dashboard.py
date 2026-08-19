from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

import paper_trading.app as web
import paper_trading.strategies as strategies
from paper_trading.config import TOP_N
from paper_trading.data_update import WARMUP_DAYS, _fetch_dividend_actions, _required_quote_dates
from paper_trading.market import DataStore
from paper_trading.models import Lot, PaperState
from paper_trading.state import StateRepository


def test_ab_strategies_each_start_with_an_independent_million() -> None:
    state = PaperState()
    assert TOP_N == 50
    assert set(state.strategies) == {"A", "B"}
    assert state.strategies["A"].dividend_weight == 0.25
    assert state.strategies["A"].voltrend_weight == 0.75
    assert state.strategies["B"].dividend_weight == 0.75
    assert state.strategies["B"].voltrend_weight == 0.25
    for strategy in state.strategies.values():
        assert strategy.dividend_book.cash + strategy.voltrend_book.cash == 1_000_000.0


def test_dashboard_exposes_ab_pipeline_interval_nav_chart_and_four_books() -> None:
    html = (Path(web.BASE_DIR) / "templates" / "index.html").read_text(encoding="utf-8")
    for number in range(1, 6):
        assert f'<span class="step-no">{number}</span>' in html
    assert "有效交易区间" in html
    assert "当日策略净值（起始净值100万元）" in html
    assert "A/B 策略累计收益曲线" in html
    assert "A/B 四分仓快照" in html
    assert "执行 AB 信号扫描" in html
    assert "执行 AB 当日流程" in html


def test_p2_reconciliation_endpoint_requires_and_accepts_both_strategies(
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
            "strategies": {
                "A": {
                    "dividend": {"cash": 250_000.0, "holdings": {}},
                    "voltrend": {"cash": 750_000.0, "holdings": {}},
                },
                "B": {
                    "dividend": {"cash": 750_000.0, "holdings": {}},
                    "voltrend": {"cash": 250_000.0, "holdings": {}},
                },
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reconciliation"]["status"] == "PASS"
    assert set(body["reconciliation"]["strategies"]) == {"A", "B"}
    assert body["p2"]["live_order_submission"] is False


def test_scan_returns_both_strategies_and_a_compatibility_view(monkeypatch) -> None:
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

    monkeypatch.setattr(
        strategies, "dividend_weights", lambda store, date: {"BBB": 0.5, "CCC": 0.5}
    )
    monkeypatch.setattr(strategies, "balanced_weights", lambda store, date: {"CCC": 1.0})
    state = PaperState()
    state.strategies["A"].dividend_book.lots = {
        "AAA": [Lot.new(100, "2026-01-01", 10.0)],
        "BBB": [Lot.new(100, "2026-01-01", 10.0)],
    }
    result = strategies.scan(state, StubStore(), "2026-08-31")
    assert set(result["strategies"]) == {"A", "B"}
    assert [row["symbol"] for row in result["strategies"]["A"]["dividend_changes"]["buy"]] == ["CCC"]
    assert [row["symbol"] for row in result["dividend_changes"]["sell"]] == ["AAA"]
    assert result["signal_status"] == "REBALANCE_DUE"


def test_nav_endpoint_returns_ab_total_and_return_series(tmp_path: Path, monkeypatch) -> None:
    repo = StateRepository(tmp_path / "state.json")
    state = PaperState(start_date="2026-08-17")
    for strategy in state.strategies.values():
        strategy.dividend_book.nav_history = [{"date": "2026-08-17", "nav": strategy.dividend_book.cash, "ret": 0.0}]
        strategy.voltrend_book.nav_history = [{"date": "2026-08-17", "nav": strategy.voltrend_book.cash, "ret": 0.0}]
    repo.save(state)
    monkeypatch.setattr(web, "repository", repo)
    body = TestClient(web.app).get("/api/nav").json()
    assert set(body["series"]) == {"A", "B"}
    assert body["series"]["A"]["total"] == [1_000_000.0]
    assert body["series"]["B"]["return"] == [0.0]


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
