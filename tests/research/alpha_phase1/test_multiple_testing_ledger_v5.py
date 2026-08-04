import numpy as np
import pandas as pd

from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg


def test_benjamini_hochberg_is_monotone_in_p_value_order():
    p_values = pd.Series([0.04, 0.001, 0.03, 0.20])
    adjusted = benjamini_hochberg(p_values)
    ordered = pd.DataFrame({"p": p_values, "q": adjusted}).sort_values("p")
    assert np.all(np.diff(ordered["q"]) >= -1e-12)
    assert (adjusted >= p_values).all()
    assert (adjusted <= 1.0).all()
