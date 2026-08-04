import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.expanded_neutralization import (
    EXPANDED_CONTROLS,
    neutralize_expanded,
)


def test_expanded_residual_is_orthogonal_to_numeric_controls():
    rng = np.random.default_rng(7)
    count = 300
    frame = pd.DataFrame(
        {
            "signal_date": pd.Timestamp("2024-01-31"),
            "eligible_evaluation": True,
            "l1_code": np.where(np.arange(count) % 2, "a", "b"),
        }
    )
    for number, column in enumerate(EXPANDED_CONTROLS):
        frame[column] = rng.normal(size=count) + number / 10
    frame["factor"] = 2 * frame["size"] - frame["beta"] + rng.normal(size=count)
    residual = neutralize_expanded(frame, "factor").dropna()
    assert len(residual) == count
    for column in EXPANDED_CONTROLS:
        assert abs(residual.corr(frame.loc[residual.index, column], method="pearson")) < 0.03
