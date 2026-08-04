"""Run the frozen V2 long-only gates over all existing Phase-1 candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.long_only_evaluation import (
    evaluate_factor,
    prepare_universe,
)


FAMILIES = (
    ("base", "factor_panel_raw.parquet", "factor_panel_metadata.json"),
    ("flow_holder", "factor_panel_flow_holder.parquet", "factor_panel_flow_holder_metadata.json"),
    ("formulaic", "factor_panel_formulaic.parquet", "factor_panel_formulaic_metadata.json"),
    ("supplemental", "factor_panel_supplemental.parquet", "factor_panel_supplemental_metadata.json"),
    ("valuation", "factor_panel_valuation.parquet", "factor_panel_valuation_metadata.json"),
    (
        "corporate_actions",
        "factor_panel_corporate_actions.parquet",
        "factor_panel_corporate_actions_metadata.json",
    ),
    (
        "cash_confirmation",
        "factor_panel_cash_confirmation.parquet",
        "factor_panel_cash_confirmation_metadata.json",
    ),
    ("margin", "factor_panel_margin.parquet", "factor_panel_margin_metadata.json"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pure-panel", type=Path, required=True)
    args = parser.parse_args()

    base = pd.read_parquet(args.artifact_dir / "factor_panel_raw.parquet")
    universe = prepare_universe(base, args.tushare_dir)
    keys = universe[["ts_code", "signal_date"]].copy()
    pure_columns: dict[str, pd.Series] = {}
    results: dict[str, object] = {}

    for family, panel_name, metadata_name in FAMILIES:
        metadata = json.loads((args.artifact_dir / metadata_name).read_text(encoding="utf-8"))
        hypotheses = metadata["factor_hypotheses"]
        if family == "base":
            family_frame = universe
        else:
            factors = list(hypotheses)
            signals = pd.read_parquet(args.artifact_dir / panel_name, columns=["ts_code", "signal_date", *factors])
            signals["signal_date"] = pd.to_datetime(signals["signal_date"])
            family_frame = universe.merge(signals, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
        for factor, hypothesis in hypotheses.items():
            result, pure = evaluate_factor(family_frame, factor, hypothesis)
            results[factor] = result
            pure_columns[f"pure_{factor}"] = pure.reset_index(drop=True)
            print(
                json.dumps(
                    {
                        "factor": factor,
                        "pure_ic": result["pure_ic"]["mean"],
                        "pure_d1": result["pure_deciles"]["d1_excess"]["mean"],
                        "pass": result["passes_all_gates"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if family != "base":
            del family_frame

    pure_panel = pd.concat([keys.reset_index(drop=True), pd.DataFrame(pure_columns)], axis=1)
    pure_names = list(pure_columns)
    sums = pd.DataFrame(0.0, index=pure_names, columns=pure_names)
    counts = pd.DataFrame(0, index=pure_names, columns=pure_names)
    for _, group in pure_panel.groupby("signal_date", sort=True):
        correlation = group[pure_names].corr(method="spearman")
        valid = correlation.notna()
        sums = sums.add(correlation.fillna(0.0), fill_value=0.0)
        counts = counts.add(valid.astype(int), fill_value=0)
    correlations = sums / counts.replace(0, np.nan)

    passing = [factor for factor, result in results.items() if result["passes_all_gates"]]
    payload = {
        "version": 2,
        "protocol": "A-share long-only; T+1 tradable close; five-style cross-sectional neutralization",
        "rows": int(len(universe)),
        "signal_months": int(universe["signal_date"].nunique()),
        "factors_tested": len(results),
        "passing_factors": passing,
        "results": results,
        "mean_monthly_cross_sectional_spearman": correlations.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_json = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_json.replace(args.output)
    temporary_panel = args.pure_panel.with_suffix(args.pure_panel.suffix + ".tmp")
    pure_panel.to_parquet(temporary_panel, index=False, compression="zstd")
    temporary_panel.replace(args.pure_panel)
    print(json.dumps({"passing_factors": passing}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
