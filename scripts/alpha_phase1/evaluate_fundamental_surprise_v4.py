"""Evaluate frozen quarterly-surprise candidates with the complete V4 style set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.expanded_neutralization import (
    EXPANDED_CONTROLS,
    neutralize_expanded,
)
from quant_trading_system.research.alpha_phase1.long_only_evaluation import prepare_universe
from quant_trading_system.research.alpha_phase1.slow_evaluation import evaluate_slow_tail_factor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--style-panel", type=Path, required=True)
    parser.add_argument("--factor-panel", type=Path, required=True)
    parser.add_argument("--factor-metadata", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pure-panel", type=Path, required=True)
    args = parser.parse_args()

    base = pd.read_parquet(args.base_panel)
    universe = prepare_universe(base, args.tushare_dir)
    keys = ["ts_code", "signal_date"]
    styles = pd.read_parquet(args.style_panel)
    styles["signal_date"] = pd.to_datetime(styles["signal_date"])
    style_columns = ["l1_code", *EXPANDED_CONTROLS]
    universe = universe.drop(columns=[column for column in style_columns if column in universe], errors="ignore")
    frame = universe.merge(styles[[*keys, *style_columns]], on=keys, how="left", validate="one_to_one")
    metadata = json.loads(args.factor_metadata.read_text(encoding="utf-8"))
    factors = list(metadata["factor_hypotheses"])
    signals = pd.read_parquet(
        args.factor_panel,
        columns=[*keys, "quality_composite", "leverage", "forward_return_3m", "entry_tradable", "exit_3m_tradable", *factors],
    )
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])
    frame = frame.drop(columns=["quality_composite", "leverage"], errors="ignore").merge(
        signals, on=keys, how="left", validate="one_to_one"
    )
    frame["forward_return"] = frame["forward_return_3m"]
    frame["eligible_quality"] = (
        frame["pit_active"]
        & frame["circ_mv"].gt(0)
        & frame["forward_return"].notna()
        & frame["entry_tradable"].fillna(False).astype(bool)
        & frame["exit_3m_tradable"].fillna(False).astype(bool)
    )
    frame["eligible_evaluation"] = frame["eligible_quality"] & frame[
        [*EXPANDED_CONTROLS, "l1_code"]
    ].notna().all(axis=1)

    results = {}
    pure_columns = {}
    for factor, hypothesis in metadata["factor_hypotheses"].items():
        pure_name = f"pure_{factor}"
        frame[pure_name] = neutralize_expanded(frame, factor)
        pure_columns[pure_name] = frame[pure_name]
        results[factor] = evaluate_slow_tail_factor(frame, factor, pure_name, hypothesis)
        print(
            json.dumps(
                {
                    "factor": factor,
                    "pure_3m": results[factor]["pure_3m"]["mean"],
                    "hac_t": results[factor]["pure_3m"]["t_stat_hac"],
                    "pass": results[factor]["passes_all_gates"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    pure = pd.DataFrame({**{key: frame[key] for key in keys}, **pure_columns})
    temporary = args.pure_panel.with_suffix(args.pure_panel.suffix + ".tmp")
    pure.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.pure_panel)
    pure_names = list(pure_columns)
    correlation_sums = pd.DataFrame(0.0, index=pure_names, columns=pure_names)
    correlation_counts = pd.DataFrame(0, index=pure_names, columns=pure_names)
    for _, group in pure.groupby("signal_date", sort=True):
        correlation = group[pure_names].corr(method="spearman")
        valid = correlation.notna()
        correlation_sums = correlation_sums.add(correlation.fillna(0.0), fill_value=0.0)
        correlation_counts = correlation_counts.add(valid.astype(int), fill_value=0)
    mean_correlation = correlation_sums / correlation_counts.replace(0, pd.NA)
    payload = {
        "version": 4,
        "protocol": "quarterly PIT; T+1 adjusted open; 3-month core; expanded styles; fixed OOS from 2023-07",
        "expanded_controls": EXPANDED_CONTROLS,
        "eligible_rows": int(frame["eligible_evaluation"].sum()),
        "results": results,
        "passing_factors": [factor for factor, result in results.items() if result["passes_all_gates"]],
        "mean_monthly_pure_spearman": mean_correlation.to_dict(),
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passing_factors": payload["passing_factors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
