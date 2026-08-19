from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from paper_trading.config import dividend_tax_rate_for_dates
from paper_trading.dividend_backfill import normalize_eastmoney, report_periods


def test_dividend_tax_uses_natural_month_and_year_boundaries() -> None:
    assert dividend_tax_rate_for_dates("2024-01-31", "2024-02-29") == 0.20
    assert dividend_tax_rate_for_dates("2024-01-31", "2024-03-01") == 0.10
    assert dividend_tax_rate_for_dates("2024-02-29", "2025-02-28") == 0.10
    assert dividend_tax_rate_for_dates("2024-02-29", "2025-03-01") == 0.0
    with pytest.raises(ValueError):
        dividend_tax_rate_for_dates(date(2024, 1, 1), date(2024, 1, 1))


def test_eastmoney_cash_ratio_is_normalized_from_per_ten_to_per_share() -> None:
    raw = pd.DataFrame(
        [
            {
                "代码": "000001",
                "现金分红-现金分红比例": 7.19,
                "股权登记日": "2024-06-13",
                "除权除息日": "2024-06-14",
                "方案进度": "实施分配",
                "最新公告日期": "2024-06-06",
            },
            {
                "代码": "600000",
                "现金分红-现金分红比例": 3.0,
                "股权登记日": None,
                "除权除息日": None,
                "方案进度": "董事会决议通过",
                "最新公告日期": "2024-04-01",
            },
        ]
    )
    result = normalize_eastmoney(raw, "20231231")
    assert result["ts_code"].tolist() == ["000001.SZ"]
    assert result["cash_div_tax"].tolist() == pytest.approx([0.719])
    assert result.iloc[0]["record_date"] == pd.Timestamp("2024-06-13")


def test_report_periods_are_semiannual_and_deterministic() -> None:
    assert report_periods(2024, 2025) == ["20240630", "20241231", "20250630", "20251231"]
