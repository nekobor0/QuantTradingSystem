import pandas as pd

from quant_trading_system.research.alpha_phase1.slow_evaluation import slow_tail_series


def test_slow_tail_uses_highest_five_percent_and_fixed_cost():
    rows = []
    for date in pd.to_datetime(["2024-01-31", "2024-02-29"]):
        for number in range(400):
            rows.append(
                {
                    "signal_date": date, "ts_code": f"{number:06d}",
                    "eligible_evaluation": True, "factor": number,
                    "forward_return": number / 10000, "l1_code": "a",
                }
            )
    frame = pd.DataFrame(rows)
    values, holdings, _ = slow_tail_series(frame, "factor")
    assert len(holdings[pd.Timestamp("2024-01-31")]) == 20
    expected = frame.iloc[380:400]["forward_return"].mean() - frame.iloc[:400]["forward_return"].mean() - 0.0005
    assert abs(values.iloc[0] - expected) < 1e-12
