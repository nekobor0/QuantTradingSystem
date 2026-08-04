from __future__ import annotations

import pandas as pd
import numpy as np

from scripts.alpha_phase1.build_event_factor_panel import (
    _holder_scores,
    _repurchase_scores,
)


def test_repurchase_uses_latest_cumulative_amount_per_plan() -> None:
    raw = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "ann_date": ["20240101", "20240115"],
            "end_date": ["20240301", "20240301"],
            "exp_date": ["20240401", "20240401"],
            "low_limit": [8.0, 8.0],
            "high_limit": [10.0, 10.0],
            "amount": [100.0, 150.0],
            "proc": ["实施", "完成"],
        }
    )

    result = _repurchase_scores(raw, [pd.Timestamp("2024-01-31")])

    assert result.loc[0, "repurchase_execution_60"] == 150.0
    assert result.loc[0, "repurchase_completion_120"] == 150.0


def test_repurchase_discards_negative_amounts() -> None:
    raw = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "ann_date": ["20240115"],
            "end_date": ["20240301"],
            "exp_date": ["20240401"],
            "low_limit": [8.0],
            "high_limit": [10.0],
            "amount": [-100.0],
            "proc": ["完成"],
        }
    )

    result = _repurchase_scores(raw, [pd.Timestamp("2024-01-31")])

    assert result.loc[0, "repurchase_execution_60"] == 0.0


def test_holder_trade_signs_actual_increase_and_decrease() -> None:
    raw = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "ann_date": ["20240110", "20240120"],
            "change_ratio": [0.3, 0.1],
            "in_de": ["IN", "DE"],
            "holder_type": ["高管", "普通股东"],
        }
    )

    result = _holder_scores(raw, [pd.Timestamp("2024-01-31")])

    assert np.isclose(result.loc[0, "holder_net_purchase_60"], 0.2)
    assert np.isclose(result.loc[0, "holder_conviction_120"], 0.35)
