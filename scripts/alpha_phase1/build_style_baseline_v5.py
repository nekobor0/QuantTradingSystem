"""Extend the frozen V4 styles with quarterly PIT Quality and Leverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.fundamental_surprise import (
    grouped_standardize,
    monthly_point_in_time,
    prepare_versions,
)
from quant_trading_system.research.alpha_phase1.style_baseline import winsorized_zscore


COMPONENT_SOURCES = {
    "baseline_value_z": "value_composite",
    "baseline_quality_z": "quality_composite",
    "baseline_investment_z": "investment",
    "baseline_momentum_z": "momentum",
    "baseline_low_resvol_z": "residual_volatility",
}


def add_baseline_score(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for _, indices in output.groupby("signal_date", sort=False).groups.items():
        for target, source in COMPONENT_SOURCES.items():
            values = -output.loc[indices, source] if target == "baseline_low_resvol_z" else output.loc[indices, source]
            output.loc[indices, target] = winsorized_zscore(values)
    components = list(COMPONENT_SOURCES)
    output["baseline_component_count"] = output[components].notna().sum(axis=1).astype("int8")
    output["style_baseline_equal_weight"] = output[components].fillna(0.0).mean(axis=1)
    output.loc[output["size"].isna(), "style_baseline_equal_weight"] = pd.NA
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--style-v4", type=Path, default=Path("artifacts/alpha_phase1/factor_panel_style_baseline_v4.parquet")
    )
    parser.add_argument(
        "--fina-indicator", type=Path, default=Path("artifacts/alpha_phase1/tushare/fina_indicator.parquet")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/alpha_phase1/factor_panel_style_baseline_v5.parquet")
    )
    parser.add_argument(
        "--metadata", type=Path, default=Path("artifacts/alpha_phase1/factor_panel_style_baseline_v5_metadata.json")
    )
    args = parser.parse_args()

    keys = ["ts_code", "signal_date"]
    style = pd.read_parquet(args.style_v4).drop(columns=["quality_composite", "leverage"])
    signal_dates = sorted(pd.Timestamp(value) for value in style["signal_date"].unique())
    versions = prepare_versions(pd.read_parquet(args.fina_indicator))
    fundamental = monthly_point_in_time(versions, signal_dates)
    fundamental["report_age_days"] = (
        fundamental["signal_date"] - fundamental["ann_date"]
    ).dt.days
    fundamental = fundamental[fundamental["report_age_days"].between(0, 250)]
    raw_columns = ["roe_waa", "grossprofit_margin", "netprofit_margin", "ocf_to_or"]
    output = style.merge(
        fundamental[[*keys, "report_age_days", "debt_to_assets", *raw_columns]],
        on=keys,
        how="left",
        validate="one_to_one",
    )
    output["standardization_group"] = np.where(
        output["financial_sector"].eq("nonfinancial"),
        output["l1_code"],
        output["financial_sector"],
    )
    output["standardization_group"] = output["standardization_group"].fillna(
        "UNCLASSIFIED"
    )
    quality_columns = []
    for source in raw_columns:
        target = f"quality_{source}_z"
        quality_columns.append(target)
        output[target] = np.nan
    output["leverage"] = np.nan
    for _, indices in output.groupby("signal_date", sort=False).groups.items():
        for source, target in zip(raw_columns, quality_columns):
            output.loc[indices, target] = grouped_standardize(
                output.loc[indices, source], output.loc[indices, "standardization_group"]
            )
        output.loc[indices, "leverage"] = grouped_standardize(
            output.loc[indices, "debt_to_assets"],
            output.loc[indices, "standardization_group"],
        )
    output["quality_composite"] = output[quality_columns].mean(axis=1).where(
        output[quality_columns].notna().sum(axis=1) >= 2
    )
    output = output.drop(
        columns=["standardization_group", "debt_to_assets", *raw_columns, *quality_columns]
    )
    output = add_baseline_score(output).sort_values(keys)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    active = output[output["size"].notna()]
    payload = {
        "version": 5,
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(keys).sum()),
        "signal_months": int(output["signal_date"].nunique()),
        "active_coverage": {
            column: float(active[column].notna().mean())
            for column in ["quality_composite", "leverage", *COMPONENT_SOURCES]
        },
        "component_count_distribution": {
            str(key): int(value)
            for key, value in active["baseline_component_count"].value_counts().sort_index().items()
        },
        "baseline": "equal weight Value + Quality + Investment + Momentum + Low Residual Volatility",
        "missing_component_protocol": "cross-sectional z-score each observed component, then neutral-impute missing component to zero; retain component count",
        "financial_protocol": "latest report version visible by ann_date at signal month end; slow-style carry-forward capped at 250 days",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
