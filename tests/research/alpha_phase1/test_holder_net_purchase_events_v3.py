from __future__ import annotations

import pandas as pd

from scripts.alpha_phase1.build_holder_net_purchase_events_v3 import aggregate_net_purchase


def test_holder_trade_aggregates_same_day_increases_and_decreases_net() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000001.SZ", "000002.SZ"],
            "ann_date": ["20240102", "20240102", "20240102", "20240102"],
            "in_de": ["IN", "IN", "DE", "DE"],
            "change_ratio": [0.2, 0.1, 0.05, 0.3],
        }
    )

    result = aggregate_net_purchase(frame).set_index("ts_code")

    assert abs(result.loc["000001.SZ", "signed_ratio"] - 0.25) < 1e-12
    assert abs(result.loc["000002.SZ", "signed_ratio"] + 0.3) < 1e-12
