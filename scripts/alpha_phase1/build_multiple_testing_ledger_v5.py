"""Build the frozen 62-trial multiple-testing ledger from existing machine results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """Return monotone Benjamini-Hochberg adjusted q-values."""
    values = p_values.astype(float)
    order = np.argsort(values.to_numpy())
    ranked = values.to_numpy()[order]
    adjusted = ranked * len(ranked) / np.arange(1, len(ranked) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1].clip(0.0, 1.0)
    output = np.empty(len(values))
    output[order] = adjusted
    return pd.Series(output, index=values.index)


def old_factor_family(name: str) -> str:
    if name.startswith("formulaic_"):
        return "formulaic_price_volume"
    if name.startswith(("margin_", "institutional_", "retail_", "smart_money_")):
        return "flow_and_margin"
    if name.startswith(("holder_", "repurchase_")):
        return "holder_and_repurchase"
    if name.startswith(("cash_", "gross_", "roe_", "fundamental_", "conservative_")):
        return "fundamental_quality"
    if name.endswith(("_yield", "_to_price", "_to_market")):
        return "value_and_fundamental_change"
    if "supply" in name:
        return "equity_supply"
    return "market_and_microstructure"


def build_ledger(artifact_dir: Path) -> pd.DataFrame:
    old = json.loads(
        (artifact_dir / "factor_evaluation_long_only_v2_59_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    new = json.loads(
        (artifact_dir / "factor_evaluation_fundamental_surprise_v4.json").read_text(
            encoding="utf-8"
        )
    )
    rows = []
    for name, result in old["results"].items():
        t_stat = float(result["pure_ic"]["t_stat"])
        observations = int(result["pure_ic"]["months"])
        rows.append(
            {
                "trial_id": len(rows) + 1,
                "factor": name,
                "family": old_factor_family(name),
                "research_version": "V2_59_frozen_snapshot",
                "primary_statistic": "pure_monthly_spearman_ic_t",
                "estimate": float(result["pure_ic"]["mean"]),
                "t_statistic": t_stat,
                "observations": observations,
                "p_value_two_sided": float(
                    2 * stats.t.sf(abs(t_stat), df=observations - 1)
                ),
                "original_decision": (
                    "PASS" if result["passes_all_gates"] else "REJECTED"
                ),
            }
        )
    for name, result in new["results"].items():
        t_stat = float(result["pure_3m"]["t_stat_hac"])
        observations = int(result["pure_3m"]["observations"])
        rows.append(
            {
                "trial_id": len(rows) + 1,
                "factor": name,
                "family": "fundamental_surprise_underreaction",
                "research_version": "V4_quarterly_PIT",
                "primary_statistic": "pure_3m_hac_t",
                "estimate": float(result["pure_3m"]["mean"]),
                "t_statistic": t_stat,
                "observations": observations,
                "p_value_two_sided": float(
                    2 * stats.t.sf(abs(t_stat), df=observations - 1)
                ),
                "original_decision": (
                    "PASS" if result["passes_all_gates"] else "REJECTED"
                ),
            }
        )
    ledger = pd.DataFrame(rows)
    if len(ledger) != 62 or ledger["factor"].duplicated().any():
        raise ValueError("expected exactly 62 unique frozen candidate trials")
    ledger["bh_q_value_global"] = benjamini_hochberg(ledger["p_value_two_sided"])
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    args = parser.parse_args()
    ledger = build_ledger(args.artifact_dir)
    csv_path = args.artifact_dir / "multiple_testing_ledger_v5.csv"
    json_path = args.artifact_dir / "multiple_testing_summary_v5.json"
    ledger.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary = {
        "candidate_trials": int(len(ledger)),
        "original_passes": int(ledger["original_decision"].eq("PASS").sum()),
        "global_bh_fdr_5pct_passes": int(ledger["bh_fdr_5pct"].sum()),
        "minimum_global_q_value": float(ledger["bh_q_value_global"].min()),
        "method": "two-sided primary-statistic p-values with global Benjamini-Hochberg FDR",
        "heterogeneous_statistic_caveat": (
            "V2 uses monthly Pure IC t statistics; V4 uses 3-month HAC t statistics."
        ),
        "source_files": [
            "factor_evaluation_long_only_v2_59_snapshot.json",
            "factor_evaluation_fundamental_surprise_v4.json",
        ],
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
