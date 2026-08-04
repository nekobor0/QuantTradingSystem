"""Build the two result-before-frozen B-level features on the V5 risk model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.expanded_neutralization import (
    neutralize_expanded,
)
from quant_trading_system.research.alpha_phase1.style_baseline import winsorized_zscore


FEATURES = ("holder_concentration_level", "price_volume_divergence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/alpha_phase1/b_feature_panel_v5.parquet"))
    parser.add_argument("--metadata", type=Path, default=Path("artifacts/alpha_phase1/b_feature_panel_v5_metadata.json"))
    args = parser.parse_args()
    keys = ["ts_code", "signal_date"]
    style = pd.read_parquet(args.artifact_dir / "factor_panel_style_baseline_v5.parquet")
    holder = pd.read_parquet(
        args.artifact_dir / "factor_panel_flow_holder.parquet",
        columns=[*keys, "holder_concentration_level"],
    )
    price_volume = pd.read_parquet(
        args.artifact_dir / "factor_panel_raw_v4_t1_open.parquet",
        columns=[*keys, "price_volume_divergence"],
    )
    frame = style.merge(holder, on=keys, validate="one_to_one").merge(
        price_volume, on=keys, validate="one_to_one"
    )
    frame["eligible_evaluation"] = frame["size"].notna() & frame["l1_code"].notna()
    pure_columns = []
    for feature in FEATURES:
        pure = f"{feature}_pure_v5"
        score = f"{feature}_score_v5"
        frame[pure] = neutralize_expanded(frame, feature)
        frame[score] = frame.groupby("signal_date")[pure].transform(winsorized_zscore)
        pure_columns.extend([pure, score])
    output = frame[[*keys, *FEATURES, *pure_columns]].sort_values(keys)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    active = frame[frame["eligible_evaluation"]]
    monthly_correlations = active.groupby("signal_date").apply(
        lambda group: group["holder_concentration_level_score_v5"].corr(
            group["price_volume_divergence_score_v5"], method="spearman"
        ),
        include_groups=False,
    )
    payload = {
        "version": 5,
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(keys).sum()),
        "active_coverage": {
            column: float(active[column].notna().mean()) for column in pure_columns
        },
        "mean_monthly_spearman_between_b_features": float(monthly_correlations.mean()),
        "role": "B-level marginal portfolio contribution only; neutral missing score is zero in portfolio combination",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
