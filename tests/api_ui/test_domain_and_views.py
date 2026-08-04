from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from quant_trading_system.api_ui.domain import AuthSession, ImportSession, UiPreference
from quant_trading_system.api_ui.errors import ValidationError
from quant_trading_system.api_ui.view_models import build_daily_decision_view

from conftest import ACCOUNT_ID, NOW


@pytest.mark.parametrize("page_size", list(range(10, 110)))
def test_valid_page_sizes_are_preserved(page_size):
    assert UiPreference("u", "dark", "Asia/Shanghai", page_size, NOW).page_size == page_size


@pytest.mark.parametrize("page_size", [-1, 0, 9, 201, 999])
def test_invalid_page_sizes_fail(page_size):
    with pytest.raises(ValidationError):
        UiPreference("u", "dark", "Asia/Shanghai", page_size, NOW)


def test_session_rejects_naive_time():
    with pytest.raises(ValidationError):
        AuthSession("u", ACCOUNT_ID, "a", "b", NOW.replace(tzinfo=None), NOW + timedelta(hours=1))


def test_import_rejects_bad_expiry():
    with pytest.raises(ValidationError):
        ImportSession(ACCOUNT_ID, "u", "a" * 64, "v1", (), 0, False, {}, NOW, NOW)


def payload():
    instrument_id = uuid4()
    return {"as_of": NOW.isoformat(), "mode": "LIVE", "hard_block": False, "blocking_reasons": [], "etf": {"daily_gate": "OPEN", "rebalance": False}, "equity": {"SELECT": 1, "KEEP": 2, "EXIT": 3}, "sleeve_contributions": [{"instrument_id": str(instrument_id), "source": "ETF"}], "net_recommendations": [{"recommendation_id": str(uuid4()), "instrument_id": str(instrument_id), "side": "BUY", "quantity": 100, "version": 2}]}


def test_view_exposes_dual_strategy_and_only_net_order():
    view = build_daily_decision_view(payload())
    assert view.etf["rebalance"] is False
    assert view.equity["SELECT"] == 1
    assert view.recommendations[0].source_label == "COMBINED_NET"


def test_hard_block_disables_approval():
    value = payload(); value["hard_block"] = True
    assert not build_daily_decision_view(value).approval_enabled


def test_duplicate_net_recommendation_fails():
    value = payload(); value["net_recommendations"].append(dict(value["net_recommendations"][0]))
    with pytest.raises(ValidationError): build_daily_decision_view(value)


def test_sleeve_order_action_fails():
    value = payload(); value["sleeve_contributions"][0]["order_action"] = "BUY"
    with pytest.raises(ValidationError): build_daily_decision_view(value)


def test_view_requires_aware_time():
    value = payload(); value["as_of"] = "2026-07-28T08:00:00"
    with pytest.raises(ValidationError): build_daily_decision_view(value)
