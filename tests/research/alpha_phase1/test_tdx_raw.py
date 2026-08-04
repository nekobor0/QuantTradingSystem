from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from quant_trading_system.research.alpha_phase1 import TdxRawQualityError, parse_research_series


def payload() -> dict:
    values = {
        "Date": ["20240102", "20240103"],
        "Open": ["10", "10.2"],
        "High": ["10.5", "10.4"],
        "Low": ["9.9", "10.1"],
        "Close": ["10.3", "10.2"],
        "Volume": ["1000", "1200"],
        "Amount": ["1.1", "1.3"],
        "ForwardFactor": ["0.9", "1.0"],
        "VolInStock": ["500000", ""],
        "ErrorId": "0",
    }
    return {"result": {"Value": {"600000.SH": values}}}


def test_extracts_factor_and_float_shares_with_aligned_dates() -> None:
    series = parse_research_series(payload())[0]
    assert series.symbol == "600000.SH"
    assert series.dates == (date(2024, 1, 2), date(2024, 1, 3))
    assert series.forward_factor == (0.9, 1.0)
    assert series.float_shares == (500000.0, None)
    assert series.rows == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["result"]["Value"]["600000.SH"].pop("ForwardFactor"), "missing list field"),
        (lambda value: value["result"]["Value"]["600000.SH"]["ForwardFactor"].pop(), "different lengths"),
        (lambda value: value["result"]["Value"]["600000.SH"]["ForwardFactor"].__setitem__(0, "0"), "must be positive"),
        (lambda value: value["result"]["Value"]["600000.SH"]["Date"].__setitem__(1, "20240102"), "strictly increasing"),
        (lambda value: value["result"]["Value"]["600000.SH"]["VolInStock"].__setitem__(0, "-1"), "must be nonnegative"),
    ],
)
def test_unsafe_research_series_fails_closed(mutate, message: str) -> None:
    value = deepcopy(payload())
    mutate(value)
    with pytest.raises(TdxRawQualityError, match=message):
        parse_research_series(value)

