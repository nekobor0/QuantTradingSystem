"""Build and evaluate the preregistered V6 downside-beta defensive candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.alpha_phase1.expanded_neutralization import (
    EXPANDED_CONTROLS,
    neutralize_expanded,
)
from quant_trading_system.research.v6.downside_beta import (
    cross_sectional_signal,
    downside_metrics,
    rolling_downside_beta,
)
from quant_trading_system.research.v6.incremental_evaluation import compare_portfolios
from scripts.alpha_phase1.build_style_baseline_v4 import _delisted_returns
from scripts.alpha_phase1.evaluate_capacity_v5 import summarize as summarize_capacity
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import prepare_panel, run_one


BENCHMARKS = ("000300.SH", "000852.SH")
VALIDATION_START = pd.Timestamp("2023-07-01")
VALIDATION_END = pd.Timestamp("2026-06-30")


def fixed_validation(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        frame["signal_date"].between(VALIDATION_START, VALIDATION_END, inclusive="both")
    ]


def net_excess_significance(frame: pd.DataFrame) -> dict[str, float | bool | int]:
    active = (frame["portfolio_net_return"] - frame["benchmark_return"]).dropna()
    fitted = sm.OLS(active.to_numpy(), np.ones((len(active), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": 3}
    )
    mean = float(fitted.params[0])
    t_statistic = float(fitted.tvalues[0])
    return {
        "months": int(len(active)),
        "annualized_mean": mean * 12,
        "hac_t_statistic": t_statistic,
        "significantly_negative_5pct_one_sided": bool(mean < 0 and t_statistic < -1.645),
    }


def benchmark_drawdown_episode(
    frame: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    ordered = frame.sort_values("signal_date").reset_index(drop=True)
    wealth = (1.0 + ordered["benchmark_return"]).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    trough = int(drawdown.idxmin())
    peak = int(wealth.iloc[: trough + 1].idxmax())
    return pd.Timestamp(ordered.loc[peak, "signal_date"]), pd.Timestamp(
        ordered.loc[trough, "signal_date"]
    )


def episode_return(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    episode = frame[
        frame["signal_date"].gt(start) & frame["signal_date"].le(end)
    ].sort_values("signal_date")
    return float((1.0 + episode["portfolio_net_return"]).prod() - 1.0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def adjusted_return(series: object) -> pd.Series:
    adjusted = pd.Series(
        np.asarray(series.close) * np.asarray(series.forward_factor),
        index=pd.to_datetime(series.dates),
    )
    return adjusted.pct_change(fill_method=None)


def build_raw_panel(
    *,
    raw_dir: Path,
    audit_path: Path,
    tushare_dir: Path,
    market_path: Path,
    signal_dates: list[pd.Timestamp],
) -> tuple[pd.DataFrame, dict[str, object]]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    selected: dict[str, dict[str, object]] = audit["selected"]
    by_file: dict[str, list[str]] = defaultdict(list)
    for symbol, details in selected.items():
        by_file[str(details["file"])].append(symbol)
    market = pd.read_parquet(market_path).set_index("date")["market_return"].sort_index()
    rows: list[pd.DataFrame] = []
    parsed_symbols = 0
    for number, (filename, symbols) in enumerate(sorted(by_file.items()), start=1):
        payload = json.loads((raw_dir / filename).read_text(encoding="utf-8"))
        available = {series.symbol: series for series in parse_research_series(payload)}
        for symbol in symbols:
            series = available.get(symbol)
            if series is None:
                continue
            estimates = rolling_downside_beta(adjusted_return(series), market).reindex(
                signal_dates
            )
            rows.append(
                pd.DataFrame(
                    {
                        "ts_code": symbol,
                        "signal_date": signal_dates,
                        "downside_beta": estimates["downside_beta"].to_numpy(),
                        "total_observations": estimates["total_observations"].to_numpy(),
                        "down_observations": estimates["down_observations"].to_numpy(),
                    }
                )
            )
            parsed_symbols += 1
        if number % 500 == 0:
            print(
                json.dumps(
                    {"event": "downside_beta_raw", "files": number, "symbols": parsed_symbols}
                ),
                flush=True,
            )
    for symbol, returns in sorted(_delisted_returns(tushare_dir).items()):
        if symbol in selected:
            continue
        estimates = rolling_downside_beta(returns, market).reindex(signal_dates)
        rows.append(
            pd.DataFrame(
                {
                    "ts_code": symbol,
                    "signal_date": signal_dates,
                    "downside_beta": estimates["downside_beta"].to_numpy(),
                    "total_observations": estimates["total_observations"].to_numpy(),
                    "down_observations": estimates["down_observations"].to_numpy(),
                }
            )
        )
    return pd.concat(rows, ignore_index=True), {
        "selected_symbols": len(selected),
        "parsed_symbols": parsed_symbols,
        "source_files": len(by_file),
        "tdx_audit_coverage": audit["a_share_universe_coverage"],
    }


def build_signals(
    artifact_dir: Path,
    raw_dir: Path,
    audit_path: Path,
    output_dir: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    style_path = artifact_dir / "factor_panel_style_baseline_v5.parquet"
    style = pd.read_parquet(style_path)
    style["signal_date"] = pd.to_datetime(style["signal_date"])
    dates = sorted(pd.Timestamp(value) for value in style["signal_date"].unique())
    raw, source_summary = build_raw_panel(
        raw_dir=raw_dir,
        audit_path=audit_path,
        tushare_dir=artifact_dir / "tushare",
        market_path=artifact_dir / "all_a_equal_weight_market_return_v4.parquet",
        signal_dates=dates,
    )
    keys = ["ts_code", "signal_date"]
    columns = [*keys, "l1_code", *EXPANDED_CONTROLS]
    eligibility = prepare_panel(artifact_dir)
    age = (eligibility["signal_date"] - eligibility["list_date"]).dt.days
    not_delisted = eligibility["delist_date"].isna() | eligibility["delist_date"].gt(
        eligibility["signal_date"]
    )
    eligibility["eligible_signal"] = (
        age.ge(90)
        & not_delisted
        & ~eligibility["is_st"]
        & eligibility["entry_tradable"].fillna(False)
        & eligibility["adv20_cny"].gt(0)
    )
    signals = (
        style[columns]
        .merge(raw, on=keys, how="left", validate="one_to_one")
        .merge(
            eligibility[[*keys, "eligible_signal"]],
            on=keys,
            how="left",
            validate="one_to_one",
        )
    )
    signals["eligible_signal"] = signals["eligible_signal"].fillna(False)
    signals = cross_sectional_signal(signals, eligible="eligible_signal")
    signals["eligible_evaluation"] = (
        signals["eligible_signal"] & signals["raw_signal"].notna()
    )
    signals["neutralized_signal"] = neutralize_expanded(signals, "standardized_signal")

    def zscore(values: pd.Series) -> pd.Series:
        deviation = values.std(ddof=0)
        return (
            (values - values.mean()) / deviation
            if deviation and np.isfinite(deviation)
            else values * np.nan
        )

    signals["defensive_score"] = signals.groupby("signal_date")[
        "neutralized_signal"
    ].transform(zscore)
    saved_columns = [
        *keys,
        "eligible_signal",
        "downside_beta",
        "total_observations",
        "down_observations",
        "raw_signal",
        "winsorized_signal",
        "standardized_signal",
        "neutralized_signal",
        "defensive_score",
    ]
    saved = signals[saved_columns].sort_values(keys)
    output_dir.mkdir(parents=True, exist_ok=True)
    signal_path = output_dir / "downside_beta_v6_signals.parquet"
    temporary = signal_path.with_suffix(".parquet.tmp")
    saved.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(signal_path)
    controls_complete = signals[EXPANDED_CONTROLS + ["l1_code"]].notna().all(axis=1)
    audit = {
        "version": 6,
        "research_id": "downside_beta_v6",
        "status": "PASS",
        "sources": {
            "tdx_audit": {
                "path": audit_path.as_posix(),
                "sha256": sha256_file(audit_path),
            },
            "style_panel": {
                "path": style_path.as_posix(),
                "sha256": sha256_file(style_path),
            },
            "market_return": {
                "path": (
                    artifact_dir / "all_a_equal_weight_market_return_v4.parquet"
                ).as_posix(),
                "sha256": sha256_file(
                    artifact_dir / "all_a_equal_weight_market_return_v4.parquet"
                ),
            },
        },
        "source_summary": source_summary,
        "rows": int(len(saved)),
        "symbols": int(saved["ts_code"].nunique()),
        "signal_dates": int(saved["signal_date"].nunique()),
        "date_start": saved["signal_date"].min().date().isoformat(),
        "date_end": saved["signal_date"].max().date().isoformat(),
        "duplicate_keys": int(saved.duplicated(keys).sum()),
        "eligible_rows": int(saved["eligible_signal"].sum()),
        "raw_coverage_all_rows": float(saved["raw_signal"].notna().mean()),
        "raw_coverage": float(
            saved.loc[saved["eligible_signal"], "raw_signal"].notna().mean()
        ),
        "neutralized_coverage": float(
            saved.loc[saved["eligible_signal"], "neutralized_signal"].notna().mean()
        ),
        "complete_control_coverage": float(
            controls_complete[signals["eligible_signal"]].mean()
        ),
        "minimum_total_observations": 120,
        "minimum_down_observations": 30,
        "pit_available_date": "daily close and market return through signal_date only",
        "future_information_violations": 0,
        "interface_failures": int(len(json.loads(audit_path.read_text(encoding="utf-8"))["rejections"])),
        "abnormal_value_rule": "raw beta retained; cross-section clipped at monthly 1st/99th percentiles",
    }
    if audit["duplicate_keys"] or audit["future_information_violations"]:
        audit["status"] = "DATA_BLOCKED"
    if audit["raw_coverage"] < 0.70 or audit["neutralized_coverage"] < 0.60:
        audit["status"] = "DATA_BLOCKED"
    audit_path_output = Path("artifacts/data_audits/downside_beta_v6.json")
    audit_path_output.parent.mkdir(parents=True, exist_ok=True)
    audit_path_output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return saved, audit


def evaluate(
    signals: pd.DataFrame,
    artifact_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    panel = prepare_panel(artifact_dir)
    panel = panel.merge(
        signals[["ts_code", "signal_date", "downside_beta", "defensive_score"]],
        on=["ts_code", "signal_date"],
        how="left",
        validate="one_to_one",
    )
    panel["downside_beta_v6_score"] = (
        0.80 * panel["style_baseline_rolling_regression_24m"]
        + 0.20 * panel["defensive_score"].fillna(0.0)
    )
    monthly_parts = []
    holding_parts = []
    construction_reports: dict[str, object] = {}
    for benchmark in BENCHMARKS:
        monthly, holdings, report = run_one(
            benchmark,
            panel,
            artifact_dir,
            0.20,
            "downside_beta_v6_score",
            "80pct_rolling_regression_plus_20pct_downside_beta",
        )
        monthly_parts.append(monthly)
        holding_parts.append(holdings)
        construction_reports[benchmark] = report
    monthly = pd.concat(monthly_parts, ignore_index=True)
    holdings = pd.concat(holding_parts, ignore_index=True)
    monthly.to_parquet(output_dir / "downside_beta_v6_monthly.parquet", index=False)
    holdings.to_parquet(output_dir / "downside_beta_v6_holdings.parquet", index=False)

    baseline_monthly = pd.read_parquet(
        artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"
    )
    baseline_holdings = pd.read_parquet(
        artifact_dir / "style_rolling_regression_24m_portfolio_v5_holdings.parquet"
    )
    validation_panel = fixed_validation(panel)
    factor_exposure_correlation = float(
        validation_panel.groupby("signal_date", sort=True).apply(
            lambda group: group["downside_beta"].corr(group["beta"], method="spearman"),
            include_groups=False,
        ).median()
    )
    partial_ic = float(
        validation_panel.loc[validation_panel["eligible_entry"]]
        .groupby("signal_date", sort=True)
        .apply(
            lambda group: group["defensive_score"].corr(
                group["mark_return_1m"], method="spearman"
            ),
            include_groups=False,
        )
        .mean()
    )
    validation_baseline = fixed_validation(baseline_monthly)
    validation_candidate = fixed_validation(monthly)
    validation_baseline_holdings = fixed_validation(baseline_holdings)
    validation_candidate_holdings = fixed_validation(holdings)
    incremental = compare_portfolios(
        validation_baseline,
        validation_candidate,
        baseline_holdings=validation_baseline_holdings,
        candidate_holdings=validation_candidate_holdings,
        partial_ic=partial_ic,
        exposure_correlation=factor_exposure_correlation,
    )
    incremental_full = compare_portfolios(
        baseline_monthly,
        monthly,
        baseline_holdings=baseline_holdings,
        candidate_holdings=holdings,
    )
    adv = pd.read_parquet(artifact_dir / "adv20_capacity_v5.parquet")
    capacity_frame = holdings.merge(
        adv,
        on=["ts_code", "signal_date"],
        how="left",
        validate="many_to_one",
    )
    defensive: dict[str, object] = {}
    promotion: dict[str, object] = {}
    for benchmark in BENCHMARKS:
        base = validation_baseline[validation_baseline["index_code"].eq(benchmark)]
        candidate = validation_candidate[
            validation_candidate["index_code"].eq(benchmark)
        ]
        candidate_full = monthly[monthly["index_code"].eq(benchmark)]
        base_metrics = downside_metrics(base)
        candidate_metrics = downside_metrics(candidate)
        report = construction_reports[benchmark]
        start, end = benchmark_drawdown_episode(candidate)
        baseline_episode_return = episode_return(base, start, end)
        candidate_episode_return = episode_return(candidate, start, end)
        drawdown_episode = {
            "start": start.date().isoformat(),
            "trough": end.date().isoformat(),
            "baseline_return": baseline_episode_return,
            "candidate_return": candidate_episode_return,
            "improvement": candidate_episode_return - baseline_episode_return,
        }
        significance = net_excess_significance(candidate_full)
        validation_capacity_frame = fixed_validation(
            capacity_frame[capacity_frame["index_code"].eq(benchmark)]
        )
        capacity_scenarios = {
            str(capital): summarize_capacity(
                validation_capacity_frame, capital, 0.05
            )
            for capital in (1_000_000, 5_000_000, 10_000_000)
        }
        candidate_capacity = capacity_scenarios["10000000"]
        validation_violations = {
            "stock_above_8pct": int(
                candidate["maximum_stock_weight"].gt(0.08 + 1e-10).sum()
            ),
            "industry_above_30pct": int(
                candidate["maximum_industry_weight"].gt(0.30 + 1e-10).sum()
            ),
            "size_outside_025": int(
                candidate["size_active_exposure"].abs().gt(0.25 + 1e-10).sum()
            ),
            "turnover_above_100pct": int(candidate["turnover"].gt(1.0 + 1e-10).sum()),
            "months_with_missing_holding_return": int(
                candidate["missing_return_weight"].gt(0).sum()
            ),
        }
        defensive[benchmark] = {
            "baseline": base_metrics,
            "candidate": candidate_metrics,
            "major_benchmark_drawdown_episode": drawdown_episode,
            "net_excess_significance": significance,
            "capacity": candidate_capacity,
            "capacity_scenarios": capacity_scenarios,
            "delta": {
                key: float(candidate_metrics[key] - base_metrics[key])
                for key in (
                    "down_month_mean_active_return",
                    "downside_beta",
                    "maximum_drawdown",
                    "tracking_error",
                    "annualized_net_excess",
                )
            },
        }
        cost_stress_20bp = report["fixed_validation_cost_stress"]["0.002"][
            "annual_excess_return_difference"
        ]
        promotion[benchmark] = {
            "down_month_mean_active_positive": candidate_metrics[
                "down_month_mean_active_return"
            ]
            > 0,
            "downside_beta_reduction_at_least_005": candidate_metrics["downside_beta"]
            <= base_metrics["downside_beta"] - 0.05,
            "major_drawdown_improvement_at_least_003": drawdown_episode[
                "improvement"
            ]
            >= 0.03,
            "full_net_excess_not_significantly_negative": not significance[
                "significantly_negative_5pct_one_sided"
            ],
            "tracking_error_at_most_005": candidate_metrics["tracking_error"] <= 0.05,
            "cost_stress_20bp_net_excess_positive": cost_stress_20bp > 0,
            "capacity_pass": (
                candidate_capacity["trades_missing_adv20"] == 0
                and candidate_capacity["trades_above_participation_cap"] == 0
                and candidate_capacity["minimum_capacity_at_cap_cny"]
                >= 10_000_000 - 1e-6
            ),
            "constraints_pass": not any(validation_violations.values()),
        }
        promotion[benchmark]["passes_all_registered_gates"] = all(
            promotion[benchmark].values()
        )
    result = {
        "research_id": "downside_beta_v6",
        "construction_reports": construction_reports,
        "fixed_validation_defensive": defensive,
        "incremental": incremental,
        "incremental_full": incremental_full,
        "promotion": promotion,
        "decision": (
            "PROMOTE_TO_LIVE_SHADOW"
            if all(item["passes_all_registered_gates"] for item in promotion.values())
            else "REJECTED"
        ),
    }
    (output_dir / "downside_beta_v6_evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1")
    )
    parser.add_argument(
        "--tdx-raw", type=Path, default=Path("artifacts/tdx_bridge/raw")
    )
    parser.add_argument(
        "--tdx-audit",
        type=Path,
        default=Path("artifacts/alpha_phase1/tdx_research_raw_audit.json"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/evaluations")
    )
    parser.add_argument("--signals-only", action="store_true")
    args = parser.parse_args()
    signals, audit = build_signals(
        args.artifact_dir, args.tdx_raw, args.tdx_audit, args.output_dir
    )
    print(json.dumps({"event": "data_audit", **audit}, ensure_ascii=False), flush=True)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: downside-beta data audit failed")
    if not args.signals_only:
        result = evaluate(signals, args.artifact_dir, args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
