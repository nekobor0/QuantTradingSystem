from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


BENCHMARKS = {
    "000300.SH": "index_weight_000300_SH.parquet",
    "000852.SH": "index_weight_000852_SH.parquet",
}
EXPOSURES = [
    "size_z",
    "beta",
    "momentum",
    "liquidity",
    "residual_volatility",
    "value_composite",
    "investment",
    "quality_composite",
    "leverage",
]


def cross_sectional_zscore(values: pd.Series) -> pd.Series:
    std = values.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(np.nan, index=values.index)
    return (values - values.mean()) / std


def audit_benchmark(
    index_code: str,
    weights: pd.DataFrame,
    panel: pd.DataFrame,
    index_daily: pd.DataFrame,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    weights = weights.copy()
    weights["signal_date"] = pd.to_datetime(weights["trade_date"], format="%Y%m%d")
    weights = weights.rename(columns={"con_code": "ts_code"})
    weights["weight_fraction"] = weights["weight"] / 100.0

    duplicate_keys = int(weights.duplicated(["signal_date", "ts_code"]).sum())
    weight_sums = weights.groupby("signal_date")["weight_fraction"].sum()
    aligned_dates = sorted(set(weights["signal_date"]) & set(panel["signal_date"]))
    aligned = weights[weights["signal_date"].isin(aligned_dates)].merge(
        panel, on=["signal_date", "ts_code"], how="left", validate="one_to_one"
    )

    index_daily = index_daily.copy()
    index_daily["date"] = pd.to_datetime(index_daily["trade_date"], format="%Y%m%d")
    index_daily = index_daily.sort_values("date").set_index("date")
    index_open_returns: dict[pd.Timestamp, float] = {}
    daily_dates = index_daily.index
    for signal_date, next_signal_date in zip(aligned_dates, aligned_dates[1:]):
        entry_candidates = daily_dates[daily_dates > signal_date]
        exit_candidates = daily_dates[daily_dates > next_signal_date]
        if len(entry_candidates) and len(exit_candidates):
            entry = float(index_daily.loc[entry_candidates[0], "open"])
            exit_ = float(index_daily.loc[exit_candidates[0], "open"])
            index_open_returns[signal_date] = exit_ / entry - 1

    monthly_rows: list[dict] = []
    industry_rows: list[dict] = []
    for date, group in aligned.groupby("signal_date", sort=True):
        total_weight = float(group["weight_fraction"].sum())
        valid_return = group["forward_return"].notna()
        return_weight = float(group.loc[valid_return, "weight_fraction"].sum())
        row = {
            "index_code": index_code,
            "signal_date": date,
            "constituents": int(len(group)),
            "weight_sum": total_weight,
            "panel_match_weight": float(
                group.loc[group["size"].notna(), "weight_fraction"].sum()
            ),
            "constituent_label_coverage_weight": return_weight,
            "synthetic_constituent_return": np.nan,
            "benchmark_return": index_open_returns.get(date, np.nan),
        }
        if return_weight > 0:
            row["synthetic_constituent_return"] = float(
                np.average(
                    group.loc[valid_return, "forward_return"],
                    weights=group.loc[valid_return, "weight_fraction"],
                )
            )
        for exposure in EXPOSURES:
            valid = group[exposure].notna()
            covered_weight = float(group.loc[valid, "weight_fraction"].sum())
            row[f"{exposure}_coverage_weight"] = covered_weight
            row[exposure] = (
                float(
                    np.average(
                        group.loc[valid, exposure],
                        weights=group.loc[valid, "weight_fraction"],
                    )
                )
                if covered_weight > 0
                else np.nan
            )
        for industry, industry_group in group.dropna(subset=["l1_code"]).groupby("l1_code"):
            industry_rows.append(
                {
                    "index_code": index_code,
                    "signal_date": date,
                    "l1_code": industry,
                    "weight": float(industry_group["weight_fraction"].sum()),
                }
            )
        monthly_rows.append(row)

    monthly = pd.DataFrame(monthly_rows)
    industries = pd.DataFrame(industry_rows)
    coverage_columns = [column for column in monthly if column.endswith("_coverage_weight")]
    report = {
        "index_code": index_code,
        "source_rows": int(len(weights)),
        "source_months": int(weights["signal_date"].nunique()),
        "source_date_min": weights["signal_date"].min().date().isoformat(),
        "source_date_max": weights["signal_date"].max().date().isoformat(),
        "duplicate_constituent_month_keys": duplicate_keys,
        "weight_sum_min": float(weight_sums.min()),
        "weight_sum_max": float(weight_sums.max()),
        "aligned_months": int(len(monthly)),
        "aligned_date_min": monthly["signal_date"].min().date().isoformat(),
        "aligned_date_max": monthly["signal_date"].max().date().isoformat(),
        "minimum_coverage_weight": {
            column: float(monthly[column].min()) for column in coverage_columns
        },
        "months_constituent_label_coverage_below_99pct": int(
            (monthly["constituent_label_coverage_weight"] < 0.99).sum()
        ),
        "months_official_benchmark_return_missing": int(monthly["benchmark_return"].isna().sum()),
        "months_panel_match_below_99pct": int((monthly["panel_match_weight"] < 0.99).sum()),
        "max_industry_weight": float(industries["weight"].max()),
    }
    return report, monthly, industries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("artifacts/alpha_phase1/benchmark_risk_audit_v5.json"),
    )
    parser.add_argument(
        "--output-monthly",
        type=Path,
        default=Path("artifacts/alpha_phase1/benchmark_monthly_v5.parquet"),
    )
    parser.add_argument(
        "--output-industries",
        type=Path,
        default=Path("artifacts/alpha_phase1/benchmark_industry_weights_v5.parquet"),
    )
    args = parser.parse_args()

    style = pd.read_parquet(args.artifact_dir / "factor_panel_style_baseline_v5.parquet")
    labels = pd.read_parquet(
        args.artifact_dir / "factor_panel_raw_v4_t1_open.parquet",
        columns=["ts_code", "signal_date", "forward_return"],
    )
    panel = style.merge(labels, on=["ts_code", "signal_date"], validate="one_to_one")
    panel["size_z"] = panel.groupby("signal_date")["size"].transform(cross_sectional_zscore)

    reports: dict[str, dict] = {}
    monthly_parts: list[pd.DataFrame] = []
    industry_parts: list[pd.DataFrame] = []
    for index_code, filename in BENCHMARKS.items():
        weights = pd.read_parquet(args.artifact_dir / "tushare" / filename)
        daily = pd.read_parquet(
            args.artifact_dir
            / "tushare"
            / f"index_daily_{index_code.replace('.', '_')}.parquet"
        )
        report, monthly, industries = audit_benchmark(index_code, weights, panel, daily)
        reports[index_code] = report
        monthly_parts.append(monthly)
        industry_parts.append(industries)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.concat(monthly_parts, ignore_index=True).to_parquet(args.output_monthly, index=False)
    pd.concat(industry_parts, ignore_index=True).to_parquet(args.output_industries, index=False)
    print(json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
