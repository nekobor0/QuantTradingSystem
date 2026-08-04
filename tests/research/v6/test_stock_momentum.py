import numpy as np
import pandas as pd

from quant_trading_system.research.v6.stock_momentum import industry_residual_momentum
from scripts.v6.run_industry_residual_momentum_v6 import evaluate_signal


def sample_frame() -> pd.DataFrame:
    rows = []
    date = pd.Timestamp("2024-01-31")
    for industry in ("A", "B", "C"):
        industry_level = {"A": 2.0, "B": 0.0, "C": -2.0}[industry]
        for number in range(20):
            rows.append(
                {
                    "ts_code": f"{industry}{number:02d}",
                    "signal_date": date,
                    "momentum": industry_level + number / 20,
                    "size": 100 + number,
                    "beta": 0.8 + number / 100,
                    "residual_volatility": 0.1 + number / 1000,
                    "l1_code": industry,
                }
            )
    return pd.DataFrame(rows)


def test_industry_levels_are_removed() -> None:
    result = industry_residual_momentum(sample_frame())
    means = result.groupby("l1_code")["neutralized_signal"].mean().abs()
    assert means.max() < 1e-10


def test_residual_is_orthogonal_to_numeric_controls() -> None:
    result = industry_residual_momentum(sample_frame()).dropna(subset=["neutralized_signal"])
    for control in ("beta", "residual_volatility"):
        assert abs(result["neutralized_signal"].corr(result[control])) < 1e-8


def test_nonserializable_attrs_are_removed() -> None:
    frame = sample_frame()
    frame.attrs["bad"] = pd.DataFrame({"x": [1]})
    assert industry_residual_momentum(frame).attrs == {}


def test_three_month_evaluation_uses_only_complete_labels() -> None:
    signals = []
    labels = []
    for date in pd.to_datetime(["2026-02-28", "2026-03-31", "2026-04-30"]):
        for number in range(20):
            key = {"ts_code": f"S{number:03d}", "signal_date": date}
            signals.append(
                {
                    **key,
                    "eligible_entry": True,
                    "entry_tradable": True,
                    "neutralized_signal": float(number),
                }
            )
            labels.append(
                {
                    **key,
                    "exit_3m_tradable": date <= pd.Timestamp("2026-03-31"),
                    "forward_return_3m": float(number) / 100 if date <= pd.Timestamp("2026-03-31") else np.nan,
                }
            )
    result = evaluate_signal(pd.DataFrame(signals), pd.DataFrame(labels))
    assert result["last_complete_label_signal_date"] == "2026-03-31"
    assert result["months"] == 2
