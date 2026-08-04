"""Minimal HTTP client for TdxQuant historical daily bars."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import TdxProtocolError, TdxTransportError

HttpOpener = Callable[..., Any]


class TdxHttpClient:
    """Call the loopback-only HTTP interface exposed by a running TQ terminal."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:17709/",
        *,
        timeout_seconds: float = 30.0,
        opener: HttpOpener = urlopen,
    ) -> None:
        if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise TdxProtocolError("TdxQuant endpoint must be loopback-only")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    def get_daily_bars(
        self,
        symbols: Sequence[str],
        *,
        start_time: str,
        end_time: str,
    ) -> Mapping[str, Any]:
        params = {
            "field_list": [
                "Date", "Open", "High", "Low", "Close", "Volume", "Amount",
                "ForwardFactor",
            ],
            "stock_list": list(symbols),
            "period": "1d",
            "start_time": start_time,
            "end_time": end_time,
            "count": -1,
            "dividend_type": "none",
            "fill_data": False,
        }
        return self._call("get_market_data", params)

    def get_stock_list(self, market: str, *, list_type: int = 1) -> tuple[Mapping[str, str], ...]:
        envelope = self._call("get_stock_list", {"market": str(market), "list_type": list_type})
        result = envelope["result"]
        values = result.get("Value") if isinstance(result, Mapping) else None
        if not isinstance(values, list):
            raise TdxProtocolError("TdxQuant stock list is missing result.Value")
        normalized: list[Mapping[str, str]] = []
        for value in values:
            if not isinstance(value, Mapping) or not str(value.get("Code", "")).strip():
                raise TdxProtocolError("TdxQuant stock list contains an invalid entry")
            normalized.append({
                "Code": str(value["Code"]).strip().upper(),
                "Name": str(value.get("Name", "")).strip(),
            })
        return tuple(normalized)

    def get_stock_info(self, symbol: str) -> Mapping[str, Any]:
        envelope = self._call(
            "get_stock_info",
            {
                "stock_code": symbol.strip().upper(),
                "field_list": [
                    "Name", "Unit", "MinPrice", "XsFlag", "HSStockKind",
                    "J_start", "IsQuitGP", "underly_setcode", "underly_code",
                ],
            },
        )
        result = envelope["result"]
        if not isinstance(result, Mapping):
            raise TdxProtocolError("TdxQuant stock info is missing result")
        return result

    def _call(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = json.dumps(
            {"id": 1, "method": method, "params": params},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise TdxTransportError("cannot reach the local TdxQuant HTTP endpoint") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TdxProtocolError("TdxQuant returned invalid JSON") from exc
        if not isinstance(result, Mapping):
            raise TdxProtocolError("TdxQuant response must be a JSON object")
        self._raise_for_top_level_error(result)
        return result

    @staticmethod
    def _raise_for_top_level_error(envelope: Mapping[str, Any]) -> None:
        result = envelope.get("result")
        if not isinstance(result, Mapping):
            raise TdxProtocolError("TdxQuant response is missing result")
        error_id = str(result.get("ErrorId", ""))
        if error_id != "0":
            message = str(result.get("Msg", "TdxQuant request failed"))
            raise TdxProtocolError(f"TdxQuant ErrorId={error_id}: {message}")
