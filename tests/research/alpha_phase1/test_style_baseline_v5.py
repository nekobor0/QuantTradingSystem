import numpy as np
import pandas as pd

from scripts.alpha_phase1.build_style_baseline_v5 import add_baseline_score


def test_baseline_neutral_imputes_a_missing_component_and_counts_it():
    frame = pd.DataFrame(
        {
            "signal_date": [pd.Timestamp("2024-01-31")] * 3,
            "size": [1.0, 2.0, 3.0],
            "value_composite": [1.0, 2.0, 3.0],
            "quality_composite": [1.0, np.nan, 3.0],
            "investment": [3.0, 2.0, 1.0],
            "momentum": [1.0, 2.0, 3.0],
            "residual_volatility": [3.0, 2.0, 1.0],
        }
    )
    result = add_baseline_score(frame)
    assert result.loc[1, "baseline_component_count"] == 4
    expected = result.loc[1, [
        "baseline_value_z", "baseline_investment_z", "baseline_momentum_z",
        "baseline_low_resvol_z",
    ]].sum() / 5
    assert np.isclose(result.loc[1, "style_baseline_equal_weight"], expected)
