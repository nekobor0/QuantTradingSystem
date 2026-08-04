import pandas as pd
import pytest

from quant_trading_system.research.v6.fundamental_selection import (
    quality_adjusted_value_signal,
    select_with_industry_cap,
)
from scripts.v6.run_quality_adjusted_value_v6 import build_strategy, signal_evaluation


def test_low_quality_is_penalized_but_high_quality_is_not_bonused() -> None:
    date = pd.Timestamp("2024-03-31")
    frame = pd.DataFrame(
        {
            "signal_date": [date] * 12,
            "baseline_value_z": [1.0] * 12,
            "baseline_quality_z": [-2.0, 2.0] + [0.0] * 10,
            "size": range(100, 112),
            "l1_code": ["A", "B"] * 6,
        }
    )
    frame.attrs["nonserializable"] = pd.DataFrame({"x": [1]})
    result = quality_adjusted_value_signal(frame)
    assert result.loc[0, "raw_signal"] == pytest.approx(-1.0)
    assert result.loc[1, "raw_signal"] == pytest.approx(1.0)
    assert result.attrs == {}


def test_selection_obeys_stock_and_industry_counts() -> None:
    rows = [
        {"ts_code": f"S{i:03d}", "l1_code": f"I{i // 10}", "raw_signal": 100 - i}
        for i in range(50)
    ]
    selected = select_with_industry_cap(pd.DataFrame(rows), count=30, max_per_industry=6)
    chosen = pd.DataFrame(rows).set_index("ts_code").loc[selected]
    assert len(selected) == 30
    assert chosen.groupby("l1_code").size().max() <= 6


def test_selection_is_deterministic_on_ties() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": ["B", "A", "C"],
            "l1_code": ["I", "I", "J"],
            "raw_signal": [1.0, 1.0, 0.0],
        }
    )
    assert select_with_industry_cap(frame, count=2, max_per_industry=2) == ["A", "B"]


def test_strategy_keeps_quarter_ranking_and_exits_deteriorated_name() -> None:
    rows = []
    for date in pd.to_datetime(["2024-03-31", "2024-04-30", "2024-05-31"]):
        for number in range(40):
            rows.append(
                {
                    "ts_code": f"S{number:03d}",
                    "signal_date": date,
                    "l1_code": f"I{number // 5}",
                    "raw_signal": float(100 - number),
                    "baseline_value_z": float(100 - number),
                    "baseline_quality_z": -2.0 if date.month == 4 and number == 0 else 0.0,
                    "eligible_entry": True,
                    "entry_tradable": True,
                    "entry_date": date + pd.Timedelta(days=1),
                    "delist_date": pd.NaT,
                    "mark_return_1m": 0.0,
                }
            )
    monthly, holdings, audit = build_strategy(pd.DataFrame(rows))
    assert (monthly["holdings"] == 30).all()
    march = set(holdings.loc[holdings["signal_date"].eq(pd.Timestamp("2024-03-31")), "ts_code"])
    april = set(holdings.loc[holdings["signal_date"].eq(pd.Timestamp("2024-04-30")), "ts_code"])
    assert "S000" in march
    assert "S000" not in april
    assert len(march - {"S000"} - april) == 0
    assert audit["deterioration_or_eligibility_exit_events"] >= 1


def test_six_month_evaluation_excludes_unfinished_future_label() -> None:
    rows = []
    label_rows = []
    for date in pd.to_datetime(["2025-10-31", "2025-11-30", "2025-12-31", "2026-01-31"]):
        for number in range(12):
            key = {"ts_code": f"S{number:03d}", "signal_date": date}
            rows.append({**key, "eligible_entry": True, "standardized_signal": float(number)})
            label_rows.append(
                {
                    **key,
                    "entry_tradable": True,
                    "exit_6m_tradable": True,
                    "forward_return_6m": float(number) / 100,
                }
            )
    result = signal_evaluation(pd.DataFrame(rows), pd.DataFrame(label_rows))
    assert result["last_complete_label_signal_date"] == "2025-12-31"
    assert result["months"] == 3


def test_six_month_evaluation_prefers_signal_side_entry_tradable() -> None:
    rows = []
    label_rows = []
    for date in pd.to_datetime(["2025-10-31", "2025-11-30"]):
        for number in range(12):
            key = {"ts_code": f"S{number:03d}", "signal_date": date}
            rows.append(
                {
                    **key,
                    "eligible_entry": True,
                    "entry_tradable": True,
                    "standardized_signal": float(number),
                }
            )
            label_rows.append(
                {
                    **key,
                    "entry_tradable": False,
                    "exit_6m_tradable": True,
                    "forward_return_6m": float(number) / 100,
                }
            )
    result = signal_evaluation(pd.DataFrame(rows), pd.DataFrame(label_rows))
    assert result["rows"] == 24
