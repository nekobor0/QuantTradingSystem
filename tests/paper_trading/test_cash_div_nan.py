from __future__ import annotations

import pandas as pd
import pytest

from paper_trading.execution import process_dividends
from paper_trading.models import Book, Lot


def test_dividend_falls_back_to_cash_div_when_cash_div_tax_is_missing() -> None:
    book = Book("dividend", 0.0, lots={"AAA": [Lot.new(100, "2026-08-01", 10.0)]})
    actions = pd.DataFrame(
        [
            {
                "ts_code": "AAA",
                "record_date": "20260819",
                "pay_date": "20260820",
                "cash_div": 0.5,
                "cash_div_tax": float("nan"),
            }
        ]
    )
    process_dividends(book, "2026-08-19", actions)
    assert book.entitlements[0].cash_div_per_share == pytest.approx(0.5)
