"""Append the preregistered V6 downside-beta trial to the frozen V5 ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg


def hac_mean_test(values: pd.Series, maxlags: int = 3) -> dict[str, float | int]:
    clean = values.dropna().astype(float)
    model = sm.OLS(clean.to_numpy(), np.ones((len(clean), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags}
    )
    estimate = float(model.params[0])
    t_statistic = float(model.tvalues[0])
    return {
        "estimate": estimate,
        "t_statistic": t_statistic,
        "observations": int(len(clean)),
        "p_value_two_sided": float(2 * norm.sf(abs(t_statistic))),
    }


def block_bootstrap_mean(
    values: pd.Series,
    *,
    samples: int = 10_000,
    block_length: int = 3,
    seed: int = 6,
) -> dict[str, float]:
    clean = values.dropna().to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    starts = np.arange(len(clean))
    estimates = np.empty(samples)
    blocks_needed = int(np.ceil(len(clean) / block_length))
    offsets = np.arange(block_length)
    for sample in range(samples):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        indices = (chosen[:, None] + offsets) % len(clean)
        estimates[sample] = clean[indices.ravel()[: len(clean)]].mean()
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return {
        "mean": float(clean.mean()),
        "ci_2_5pct": float(lower),
        "ci_97_5pct": float(upper),
    }


def downside_improvement_series(
    baseline: pd.DataFrame, candidate: pd.DataFrame
) -> pd.Series:
    keys = ["index_code", "signal_date"]
    merged = baseline.merge(candidate, on=keys, suffixes=("_base", "_candidate"))
    validation = merged[merged["signal_date"].ge("2023-07-01")]
    down = validation["benchmark_return_base"].lt(0)
    down_rows = validation.loc[down].assign(
        improvement=(
            validation.loc[down, "portfolio_net_return_candidate"]
            - validation.loc[down, "portfolio_net_return_base"]
        )
    )
    # The two benchmark sleeves share the same calendar and market shocks.
    # Average them by month before HAC rather than double-counting correlated rows.
    return down_rows.groupby("signal_date", sort=True)["improvement"].mean()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v5-ledger",
        type=Path,
        default=Path("artifacts/alpha_phase1/multiple_testing_ledger_v5.csv"),
    )
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1")
    )
    parser.add_argument(
        "--evaluation-dir", type=Path, default=Path("artifacts/evaluations")
    )
    args = parser.parse_args()
    baseline = pd.read_parquet(
        args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"
    )
    candidate = pd.read_parquet(
        args.evaluation_dir / "downside_beta_v6_monthly.parquet"
    )
    improvement = downside_improvement_series(baseline, candidate)
    test = hac_mean_test(improvement)
    bootstrap = block_bootstrap_mean(improvement)
    ledger = pd.read_csv(args.v5_ledger)
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": "downside_beta_v6",
        "family": "cross_sectional_defense",
        "research_version": "V6_preregistered",
        "primary_statistic": "fixed_validation_down_month_active_delta_hac_t",
        **test,
        "original_decision": "REJECTED",
    }
    ledger = pd.concat([ledger.drop(columns=["bh_q_value_global", "bh_fdr_5pct"]), pd.DataFrame([trial])])
    ledger["bh_q_value_global"] = benjamini_hochberg(ledger["p_value_two_sided"])
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    output_csv = args.evaluation_dir / "multiple_testing_ledger_v6.csv"
    ledger.to_csv(output_csv, index=False, encoding="utf-8-sig")
    summary = {
        "candidate_trials": int(len(ledger)),
        "new_trial": trial,
        "new_trial_q_value": float(ledger.iloc[-1]["bh_q_value_global"]),
        "new_trial_bh_fdr_5pct": bool(ledger.iloc[-1]["bh_fdr_5pct"]),
        "block_bootstrap": bootstrap,
        "decision": "REJECTED",
        "reason": "registered downside-beta and drawdown improvement gates failed",
    }
    (args.evaluation_dir / "multiple_testing_summary_v6.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
