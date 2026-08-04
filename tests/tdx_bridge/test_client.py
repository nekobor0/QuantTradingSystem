from __future__ import annotations

import json

import pytest

from quant_trading_system.tdx_bridge import TdxHttpClient, TdxProtocolError


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_http_client_freezes_safe_historical_parameters() -> None:
    captured: dict = {}

    def opener(request, *, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse({"id": 1, "result": {"ErrorId": "0", "Value": {}}})

    client = TdxHttpClient(timeout_seconds=12, opener=opener)
    client.get_daily_bars(["600000.SH"], start_time="20240101", end_time="20240131")

    params = captured["body"]["params"]
    assert captured["body"]["method"] == "get_market_data"
    assert params["period"] == "1d"
    assert params["count"] == -1
    assert params["dividend_type"] == "none"
    assert params["fill_data"] is False
    assert params["stock_list"] == ["600000.SH"]
    assert captured["timeout"] == 12


def test_http_client_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(TdxProtocolError, match="loopback"):
        TdxHttpClient("https://example.com/tdx")


def test_http_client_surfaces_tdx_error() -> None:
    def opener(_request, *, timeout):
        assert timeout == 30
        return FakeResponse({"id": 1, "result": {"ErrorId": "9", "Msg": "bad request"}})

    with pytest.raises(TdxProtocolError, match="ErrorId=9"):
        TdxHttpClient(opener=opener).get_daily_bars(
            ["600000.SH"], start_time="20240101", end_time="20240131"
        )


def test_http_client_reads_stock_list_and_reference_info() -> None:
    responses = iter([
        {"id": 1, "result": {"ErrorId": "0", "Value": [
            {"Code": "600000.sh", "Name": "浦发银行"},
        ]}},
        {"id": 1, "result": {"ErrorId": "0", "Name": "浦发银行", "J_start": "19991110"}},
    ])

    def opener(_request, *, timeout):
        assert timeout == 30
        return FakeResponse(next(responses))

    client = TdxHttpClient(opener=opener)
    assert client.get_stock_list("5") == ({"Code": "600000.SH", "Name": "浦发银行"},)
    assert client.get_stock_info("600000.sh")["J_start"] == "19991110"
