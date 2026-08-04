"""Run the frozen P0 monthly style Baseline against both V5 benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    build_adaptive_composite_scores,
    construct_industry_rotation_target,
    enforce_execution_and_turnover,
    performance_metrics,
    repair_size_exposure,
)


BENCHMARKS = ("000300.SH", "000852.SH")


def zscore(values: pd.Series) -> pd.Series:
    std = values.std(ddof=0)
    return (values - values.mean()) / std if std and np.isfinite(std) else values * np.nan


def prepare_panel(artifact_dir: Path) -> pd.DataFrame:
    style = pd.read_parquet(artifact_dir / "factor_panel_style_baseline_v5.parquet")
    execution = pd.read_parquet(artifact_dir / "portfolio_execution_labels_v5.parquet")
    panel = style.merge(execution, on=["ts_code", "signal_date"], validate="one_to_one")
    adv = pd.read_parquet(artifact_dir / "adv20_capacity_v5.parquet")
    panel = panel.merge(adv, on=["ts_code", "signal_date", "entry_date"], validate="one_to_one")
    b_features = pd.read_parquet(artifact_dir / "b_feature_panel_v5.parquet")
    panel = panel.merge(b_features, on=["ts_code", "signal_date"], validate="one_to_one")
    panel["baseline_score_v5"] = panel.groupby("signal_date")[
        "style_baseline_equal_weight"
    ].transform(zscore)
    panel["holder_enhanced_score_v5"] = (
        0.9 * panel["baseline_score_v5"]
        + 0.1 * panel["holder_concentration_level_score_v5"].fillna(0.0)
    )
    panel["price_volume_enhanced_score_v5"] = (
        0.9 * panel["baseline_score_v5"]
        + 0.1 * panel["price_volume_divergence_score_v5"].fillna(0.0)
    )
    panel["both_b_enhanced_score_v5"] = (
        0.8 * panel["baseline_score_v5"]
        + 0.1 * panel["holder_concentration_level_score_v5"].fillna(0.0)
        + 0.1 * panel["price_volume_divergence_score_v5"].fillna(0.0)
    )
    panel, adaptive_weights = build_adaptive_composite_scores(panel)
    panel["size_z"] = panel.groupby("signal_date")["size"].transform(zscore)

    basic = pd.read_parquet(
        artifact_dir / "tushare" / "stock_basic.parquet",
        columns=["ts_code", "list_date", "delist_date"],
    )
    basic["list_date"] = pd.to_datetime(basic["list_date"], errors="coerce")
    basic["delist_date"] = pd.to_datetime(basic["delist_date"], errors="coerce")
    panel = panel.merge(basic, on="ts_code", how="left", validate="many_to_one")

    st = pd.read_parquet(
        artifact_dir / "tushare" / "stock_st_month_end.parquet",
        columns=["ts_code", "trade_date"],
    ).drop_duplicates()
    st["signal_date"] = pd.to_datetime(st.pop("trade_date"), format="%Y%m%d")
    st["is_st"] = True
    panel = panel.merge(st, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    panel["is_st"] = panel["is_st"].eq(True)
    age = (panel["signal_date"] - panel["list_date"]).dt.days
    not_delisted = panel["delist_date"].isna() | panel["delist_date"].gt(panel["signal_date"])
    panel["eligible_entry"] = (
        age.ge(90)
        & not_delisted
        & ~panel["is_st"]
        & panel["entry_tradable"].fillna(False)
        & panel["mark_return_1m"].notna()
        & panel["adv20_cny"].gt(0)
    )
    panel.attrs["adaptive_weights"] = adaptive_weights
    return panel


def run_one(
    index_code: str,
    panel: pd.DataFrame,
    artifact_dir: Path,
    active_fraction: float,
    score_column: str,
    construction_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    weights = pd.read_parquet(
        artifact_dir / "tushare" / f"index_weight_{index_code.replace('.', '_')}.parquet"
    )
    weights["signal_date"] = pd.to_datetime(weights["trade_date"], format="%Y%m%d")
    weights = weights.rename(columns={"con_code": "ts_code"})
    official = pd.read_parquet(artifact_dir / "benchmark_monthly_v5.parquet")
    official = official[official["index_code"].eq(index_code)].set_index("signal_date")

    pretrade = pd.Series(dtype=float)
    monthly_rows = []
    holding_rows = []
    dates = sorted(set(panel["signal_date"]) & set(weights["signal_date"]))
    for signal_date in dates:
        benchmark_return = official["benchmark_return"].get(signal_date, np.nan)
        if not np.isfinite(benchmark_return):
            continue
        month = panel[panel["signal_date"].eq(signal_date)].copy()
        benchmark = weights[weights["signal_date"].eq(signal_date)].set_index("ts_code")["weight"] / 100
        benchmark_size_sample = month.set_index("ts_code")["size_z"].reindex(benchmark.index)
        valid_benchmark_size = benchmark_size_sample.notna()
        benchmark_size = float(
            np.average(
                benchmark_size_sample[valid_benchmark_size],
                weights=benchmark[valid_benchmark_size],
            )
        )
        target = construct_industry_rotation_target(
            month,
            benchmark,
            active_fraction=active_fraction,
            benchmark_size_exposure=benchmark_size,
            size_active_cap=0.20,
            receiver_addition_cap=month.set_index("ts_code")["adv20_cny"] * 0.05 / 10_000_000,
            score_column=score_column,
        )
        month_indexed = month.set_index("ts_code")
        forced_exit = month_indexed["delist_date"].notna() & month_indexed["delist_date"].le(
            month_indexed["entry_date"]
        )
        entry_tradable = month_indexed["entry_tradable"].fillna(False) | forced_exit
        actual, turnover = enforce_execution_and_turnover(
            target, pretrade, entry_tradable, turnover_cap=1.0
        )
        indexed = month_indexed
        repair_universe = indexed[indexed["size_z"].notna() & indexed["l1_code"].notna()]
        unrepairable = actual[~actual.index.isin(repair_universe.index)]
        repaired = repair_size_exposure(
            actual.reindex(repair_universe.index).fillna(0.0),
            repair_universe,
            benchmark_size,
            cap=0.20,
            stock_cap=0.08,
            movable=entry_tradable,
            receivable=indexed["eligible_entry"],
        )
        actual = pd.concat([repaired[repaired > 1e-14], unrepairable])
        actual = actual[actual > 1e-14]
        turnover = 0.5 * float(
            (
                actual.reindex(actual.index.union(pretrade.index)).fillna(0.0)
                - pretrade.reindex(actual.index.union(pretrade.index)).fillna(0.0)
            ).abs().sum()
        )
        returns = indexed["mark_return_1m"].reindex(actual.index)
        missing_return_weight = float(actual[returns.isna()].sum())
        realized = returns.fillna(-1.0)
        gross_return = float((actual * realized).sum())
        cost = turnover * 0.0005
        net_return = gross_return - cost

        industry_weights = actual.groupby(indexed["l1_code"].reindex(actual.index)).sum()
        size_exposure = float((actual * indexed["size_z"].reindex(actual.index)).sum())
        monthly_rows.append(
            {
                "index_code": index_code,
                "signal_date": signal_date,
                "portfolio_gross_return": gross_return,
                "portfolio_net_return": net_return,
                "benchmark_return": benchmark_return,
                "turnover": turnover,
                "cost": cost,
                "holdings": int(len(actual)),
                "maximum_stock_weight": float(actual.max()),
                "maximum_industry_weight": float(industry_weights.max()),
                "size_active_exposure": size_exposure - benchmark_size,
                "missing_return_weight": missing_return_weight,
            }
        )
        holding_rows.extend(
            {
                "index_code": index_code,
                "signal_date": signal_date,
                "ts_code": name,
                "weight": float(value),
                "trade_weight": float(value - pretrade.get(name, 0.0)),
            }
            for name, value in actual.items()
        )
        portfolio_growth = 1.0 + gross_return
        pretrade = actual * (1.0 + realized) / portfolio_growth if portfolio_growth > 0 else actual
        pretrade = pretrade[pretrade > 1e-14]

    monthly = pd.DataFrame(monthly_rows)
    holdings = pd.DataFrame(holding_rows)
    train = monthly[monthly["signal_date"].le("2023-06-30")]
    validation = monthly[monthly["signal_date"].ge("2023-07-01")]
    report = {
        "index_code": index_code,
        "construction": {
            "name": construction_name,
            "active_fraction": active_fraction,
            "receiver_count_per_industry": 10,
            "monthly_one_way_turnover_cap": 1.0,
            "round_trip_cost": 0.0005,
            "internal_size_buffer": 0.20,
        },
        "full": performance_metrics(monthly),
        "train": performance_metrics(train),
        "fixed_validation": performance_metrics(validation),
        "fixed_validation_cost_stress": {
            str(rate): performance_metrics(
                validation.assign(
                    portfolio_net_return=validation["portfolio_gross_return"]
                    - validation["turnover"] * rate
                )
            )
            for rate in (0.0005, 0.001, 0.002)
        },
        "constraint_violations": {
            "stock_above_8pct": int(monthly["maximum_stock_weight"].gt(0.08 + 1e-10).sum()),
            "industry_above_30pct": int(monthly["maximum_industry_weight"].gt(0.30 + 1e-10).sum()),
            "size_outside_025": int(monthly["size_active_exposure"].abs().gt(0.25 + 1e-10).sum()),
            "turnover_above_100pct": int(monthly["turnover"].gt(1.0 + 1e-10).sum()),
            "months_with_missing_holding_return": int(monthly["missing_return_weight"].gt(0).sum()),
        },
    }
    return monthly, holdings, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--active-fraction", type=float, default=0.20)
    parser.add_argument(
        "--variant",
        choices=[
            "baseline",
            "holder",
            "price_volume",
            "both_b",
            "historical_icir",
            "rolling_regression_24m",
        ],
        default="baseline",
    )
    args = parser.parse_args()
    variants = {
        "baseline": ("baseline_score_v5", "P0_equal_style_industry_rotation"),
        "holder": ("holder_enhanced_score_v5", "P0_plus_10pct_holder_concentration"),
        "price_volume": ("price_volume_enhanced_score_v5", "P0_plus_10pct_price_volume_divergence"),
        "both_b": ("both_b_enhanced_score_v5", "P0_plus_two_10pct_B_features"),
        "historical_icir": (
            "style_baseline_historical_icir",
            "historical_ICIR_style_composite",
        ),
        "rolling_regression_24m": (
            "style_baseline_rolling_regression_24m",
            "trailing_24m_regression_style_composite",
        ),
    }
    score_column, construction_name = variants[args.variant]
    panel = prepare_panel(args.artifact_dir)
    if args.variant in {"historical_icir", "rolling_regression_24m"}:
        panel.attrs["adaptive_weights"].to_parquet(
            args.artifact_dir / "adaptive_style_weights_v5.parquet", index=False
        )
    monthly_parts = []
    holding_parts = []
    reports = {}
    for index_code in BENCHMARKS:
        monthly, holdings, report = run_one(
            index_code,
            panel,
            args.artifact_dir,
            args.active_fraction,
            score_column,
            construction_name,
        )
        monthly_parts.append(monthly)
        holding_parts.append(holdings)
        reports[index_code] = report
    stem = "style_baseline_portfolio_v5" if args.variant == "baseline" else f"style_{args.variant}_portfolio_v5"
    pd.concat(monthly_parts, ignore_index=True).to_parquet(
        args.artifact_dir / f"{stem}_monthly.parquet", index=False
    )
    pd.concat(holding_parts, ignore_index=True).to_parquet(
        args.artifact_dir / f"{stem}_holdings.parquet", index=False
    )
    output = args.artifact_dir / f"{stem}_evaluation.json"
    output.write_text(json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
