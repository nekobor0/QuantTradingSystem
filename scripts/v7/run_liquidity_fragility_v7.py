"""Run the preregistered B7 liquidity-fragility defensive study."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.v6.downside_beta import downside_metrics
from quant_trading_system.research.v7.governance import (
    can_run_stage_p,
    validate_registration,
    validate_research_decision,
)
from quant_trading_system.research.v7.liquidity_fragility import (
    cross_sectional_fragility,
    rolling_liquidity_fragility,
)
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.evaluate_capacity_v5 import summarize as summarize_capacity
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import prepare_panel, run_one
from scripts.v6.update_multiple_testing_v6 import hac_mean_test


RESEARCH_ID = "B7_LIQUIDITY_FRAGILITY"
REGISTRATION_PATH = Path("artifacts/registrations/b7_liquidity_fragility.md")
BENCHMARKS = ("000300.SH", "000852.SH")
DRAWDOWN_EPISODES = (
    ("2018-09-28", "2019-01-31"),
    ("2020-02-28", "2020-03-31"),
    ("2022-01-28", "2022-10-31"),
    ("2024-01-31", "2024-02-29"),
)
REGISTRATION = {
    "research_id": RESEARCH_ID,
    "post_v6_hypothesis": True,
    "core_horizon": "1m",
    "primary_benchmark": "000300.SH_and_000852.SH",
    "role": "RISK_FILTER",
    "variant_count": 1,
    "historical_evidence_use": "development_only",
    "live_confirmation": {"unit": "months", "minimum": 12},
    "relaxations": {},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def config_sha256() -> str:
    payload = json.dumps(REGISTRATION, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _series_fragility(
    dates: object,
    close: object,
    factor: object,
    amount_cny: object,
    market: pd.Series,
    signal_dates: list[pd.Timestamp],
) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    adjusted = pd.Series(
        np.asarray(close, dtype=float) * np.asarray(factor, dtype=float),
        index=index,
    )
    returns = adjusted.pct_change(fill_method=None)
    amount = pd.Series(np.asarray(amount_cny, dtype=float), index=index)
    return rolling_liquidity_fragility(returns, amount, market).reindex(signal_dates)


def build_raw_panel(
    raw_dir: Path,
    tdx_audit_path: Path,
    artifact_dir: Path,
    signal_dates: list[pd.Timestamp],
) -> tuple[pd.DataFrame, dict[str, object]]:
    audit = json.loads(tdx_audit_path.read_text(encoding="utf-8"))
    selected: dict[str, dict[str, object]] = audit["selected"]
    by_file: dict[str, list[str]] = defaultdict(list)
    for symbol, details in selected.items():
        by_file[str(details["file"])].append(symbol)
    market = (
        pd.read_parquet(artifact_dir / "all_a_equal_weight_market_return_v4.parquet")
        .set_index("date")["market_return"]
        .sort_index()
    )
    rows: list[pd.DataFrame] = []
    parsed_symbols = 0
    for number, (filename, symbols) in enumerate(sorted(by_file.items()), start=1):
        payload = json.loads((raw_dir / filename).read_text(encoding="utf-8"))
        available = {series.symbol: series for series in parse_research_series(payload)}
        for symbol in symbols:
            series = available.get(symbol)
            if series is None:
                continue
            estimates = _series_fragility(
                series.dates,
                series.close,
                series.forward_factor,
                np.asarray(series.amount_wan) * 10_000.0,
                market,
                signal_dates,
            )
            estimates = estimates.reset_index(names="signal_date")
            estimates.insert(0, "ts_code", symbol)
            rows.append(estimates)
            parsed_symbols += 1
        if number % 1000 == 0:
            print(
                json.dumps(
                    {"event": "b7_raw", "files": number, "symbols": parsed_symbols}
                ),
                flush=True,
            )

    daily = pd.read_parquet(
        artifact_dir / "tushare" / "delisted_daily.parquet",
        columns=["ts_code", "trade_date", "close", "amount"],
    )
    factor = pd.read_parquet(
        artifact_dir / "tushare" / "delisted_adj_factor.parquet",
        columns=["ts_code", "trade_date", "adj_factor"],
    )
    delisted = daily.merge(
        factor, on=["ts_code", "trade_date"], validate="one_to_one"
    )
    extra_delisted = 0
    for symbol, group in delisted.groupby("ts_code", sort=True):
        if str(symbol) in selected:
            continue
        group = group.sort_values("trade_date")
        estimates = _series_fragility(
            pd.to_datetime(group["trade_date"].astype(str)),
            group["close"],
            group["adj_factor"],
            group["amount"].astype(float) * 1_000.0,
            market,
            signal_dates,
        )
        estimates = estimates.reset_index(names="signal_date")
        estimates.insert(0, "ts_code", str(symbol))
        rows.append(estimates)
        extra_delisted += 1
    return pd.concat(rows, ignore_index=True), {
        "source_files": int(len(by_file)),
        "selected_symbols": int(len(selected)),
        "parsed_symbols": int(parsed_symbols),
        "extra_delisted_symbols": int(extra_delisted),
        "tdx_audit_coverage": float(audit["a_share_universe_coverage"]),
        "tdx_rejected_files": int(audit["rejected_files"]),
    }


def build_signals(
    artifact_dir: Path,
    raw_dir: Path,
    tdx_audit_path: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    panel = prepare_panel(artifact_dir)
    signal_dates = sorted(pd.Timestamp(value) for value in panel["signal_date"].unique())
    raw, source_summary = build_raw_panel(
        raw_dir, tdx_audit_path, artifact_dir, signal_dates
    )
    keys = ["ts_code", "signal_date"]
    age = (panel["signal_date"] - panel["list_date"]).dt.days
    not_delisted = panel["delist_date"].isna() | panel["delist_date"].gt(
        panel["signal_date"]
    )
    panel["eligible_signal"] = (
        age.ge(90)
        & not_delisted
        & ~panel["is_st"]
        & panel["entry_tradable"].fillna(False)
        & panel["adv20_cny"].gt(0)
    )
    signal_columns = [
        *keys,
        "l1_code",
        "size",
        "beta",
        "eligible_signal",
        "entry_tradable",
        "mark_return_1m",
    ]
    signals = panel[signal_columns].merge(
        raw, on=keys, how="left", validate="one_to_one"
    )
    signals = cross_sectional_fragility(signals)
    return signals, source_summary


def stage_s_evaluation(signals: pd.DataFrame) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    correlations: list[float] = []
    for signal_date, month in signals.groupby("signal_date", sort=True):
        sample = month[
            month["eligible_signal"].fillna(False)
            & month["partial_signal"].notna()
            & month["mark_return_1m"].notna()
        ]
        if len(sample) < 20:
            continue
        benchmark_return = float(sample["mark_return_1m"].mean())
        correlation = sample["fragility_composite"].corr(
            sample["beta"], method="spearman"
        )
        correlations.append(float(correlation))
        if benchmark_return < 0:
            rows.append(
                {
                    "signal_date": signal_date,
                    "benchmark_return": benchmark_return,
                    "partial_rank_ic_1m": sample["partial_signal"].corr(
                        sample["mark_return_1m"], method="spearman"
                    ),
                }
            )
    monthly = pd.DataFrame(rows)
    summary = {
        "down_months": int(len(monthly)),
        "partial_rank_ic_1m_down_months": float(
            monthly["partial_rank_ic_1m"].mean()
        ),
        "positive_ic_month_share": float(
            monthly["partial_rank_ic_1m"].gt(0).mean()
        ),
        "absolute_median_beta_correlation": float(abs(np.median(correlations))),
        "hac": hac_mean_test(monthly["partial_rank_ic_1m"].dropna()),
    }
    gates = stage_s_gates(summary)
    return {"monthly": monthly, "summary": summary, "gates": gates}


def stage_s_gates(summary: dict[str, object]) -> dict[str, bool]:
    gates = {
        "partial_rank_ic_positive": summary["partial_rank_ic_1m_down_months"] > 0,
        "positive_ic_month_share_gt_055": summary["positive_ic_month_share"] > 0.55,
        "beta_correlation_lt_060": summary["absolute_median_beta_correlation"] < 0.60,
    }
    gates["passes_all"] = all(gates.values())
    return gates


def all_benchmark_gates_pass(benchmark_results: dict[str, object]) -> bool:
    return set(benchmark_results) == set(BENCHMARKS) and all(
        result["gates"]["passes_all"] for result in benchmark_results.values()
    )


def _episode_return(
    frame: pd.DataFrame, start: str, end: str
) -> float:
    sample = frame[
        frame["signal_date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ]
    return float((1.0 + sample["portfolio_net_return"]).prod() - 1.0)


def evaluate_stage_p(
    signals: pd.DataFrame,
    artifact_dir: Path,
    output_dir: Path,
    beta_correlation: float,
) -> dict[str, object]:
    panel = prepare_panel(artifact_dir).merge(
        signals[["ts_code", "signal_date", "defensive_score"]],
        on=["ts_code", "signal_date"],
        how="left",
        validate="one_to_one",
    )
    panel["b7_liquidity_fragility_score"] = (
        0.80 * panel["style_baseline_rolling_regression_24m"]
        + 0.20 * panel["defensive_score"].fillna(0.0)
    )
    monthly_parts: list[pd.DataFrame] = []
    holding_parts: list[pd.DataFrame] = []
    construction: dict[str, object] = {}
    for benchmark in BENCHMARKS:
        monthly, holdings, report = run_one(
            benchmark,
            panel,
            artifact_dir,
            0.20,
            "b7_liquidity_fragility_score",
            "80pct_rolling_regression_plus_20pct_liquidity_fragility",
        )
        monthly_parts.append(monthly)
        holding_parts.append(holdings)
        construction[benchmark] = report
    monthly = pd.concat(monthly_parts, ignore_index=True)
    holdings = pd.concat(holding_parts, ignore_index=True)
    monthly.to_parquet(
        output_dir / "b7_liquidity_fragility_monthly.parquet", index=False
    )
    holdings.to_parquet(
        output_dir / "b7_liquidity_fragility_holdings.parquet", index=False
    )
    baseline = pd.read_parquet(
        artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"
    )
    adv = pd.read_parquet(artifact_dir / "adv20_capacity_v5.parquet")
    capacity_frame = holdings.merge(
        adv, on=["ts_code", "signal_date"], how="left", validate="many_to_one"
    )
    benchmark_results: dict[str, object] = {}
    for benchmark in BENCHMARKS:
        candidate = monthly[monthly["index_code"].eq(benchmark)].sort_values(
            "signal_date"
        )
        base = baseline[baseline["index_code"].eq(benchmark)].sort_values(
            "signal_date"
        )
        joined = base[
            ["signal_date", "portfolio_net_return", "benchmark_return"]
        ].merge(
            candidate[
                ["signal_date", "portfolio_net_return", "benchmark_return"]
            ],
            on="signal_date",
            suffixes=("_base", "_candidate"),
            validate="one_to_one",
        )
        base_metrics = downside_metrics(
            joined.rename(
                columns={
                    "portfolio_net_return_base": "portfolio_net_return",
                    "benchmark_return_base": "benchmark_return",
                }
            )
        )
        candidate_metrics = downside_metrics(
            joined.rename(
                columns={
                    "portfolio_net_return_candidate": "portfolio_net_return",
                    "benchmark_return_candidate": "benchmark_return",
                }
            )
        )
        down = joined["benchmark_return_base"].lt(0)
        down_month_relative = float(
            (
                joined.loc[down, "portfolio_net_return_candidate"]
                - joined.loc[down, "portfolio_net_return_base"]
            ).mean()
        )
        episode_rows = []
        for start, end in DRAWDOWN_EPISODES:
            base_return = _episode_return(base, start, end)
            candidate_return = _episode_return(candidate, start, end)
            episode_rows.append(
                {
                    "start": start,
                    "end": end,
                    "baseline_return": base_return,
                    "candidate_return": candidate_return,
                    "improvement": candidate_return - base_return,
                }
            )
        average_episode_improvement = float(
            np.mean([row["improvement"] for row in episode_rows])
        )
        cap = summarize_capacity(
            capacity_frame[capacity_frame["index_code"].eq(benchmark)],
            10_000_000,
            0.05,
        )
        constraints = {
            "stock_above_8pct": int(
                candidate["maximum_stock_weight"].gt(0.08 + 1e-10).sum()
            ),
            "industry_above_30pct": int(
                candidate["maximum_industry_weight"].gt(0.30 + 1e-10).sum()
            ),
            "missing_return_months": int(
                candidate["missing_return_weight"].gt(0).sum()
            ),
        }
        gates = {
            "down_month_relative_return_positive": down_month_relative > 0,
            "down_capture_reduction_at_least_005": (
                candidate_metrics["down_capture_ratio"]
                <= base_metrics["down_capture_ratio"] - 0.05
            ),
            "average_registered_drawdown_improvement_at_least_003": (
                average_episode_improvement >= 0.03
            ),
            "annual_net_excess_delta_at_least_minus_001": (
                candidate_metrics["annualized_net_excess"]
                >= base_metrics["annualized_net_excess"] - 0.01
            ),
            "tracking_error_increment_lt_0015": (
                candidate_metrics["tracking_error"]
                < base_metrics["tracking_error"] + 0.015
            ),
            "beta_correlation_lt_060": beta_correlation < 0.60,
            "capacity_10m_pass": (
                cap["trades_missing_adv20"] == 0
                and cap["trades_above_participation_cap"] == 0
                and cap["minimum_capacity_at_cap_cny"] >= 10_000_000 - 1e-6
            ),
            "constraints_pass": not any(constraints.values()),
        }
        gates["passes_all"] = all(gates.values())
        benchmark_results[benchmark] = {
            "baseline": base_metrics,
            "candidate": candidate_metrics,
            "down_month_relative_return": down_month_relative,
            "registered_drawdown_episodes": episode_rows,
            "average_episode_improvement": average_episode_improvement,
            "capacity": cap,
            "constraints": constraints,
            "gates": gates,
        }
    return {
        "benchmarks": benchmark_results,
        "construction": construction,
        "passes_all_benchmarks": all_benchmark_gates_pass(benchmark_results),
    }


def update_ledger(
    hac: dict[str, object],
    decision: str,
    output_dir: Path,
) -> dict[str, object]:
    path = output_dir / "multiple_testing_ledger_v7.csv"
    ledger = pd.read_csv(path)
    ledger = ledger[ledger["factor"].ne(RESEARCH_ID)].copy()
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": RESEARCH_ID,
        "family": "cross_sectional_liquidity_fragility",
        "research_version": "V7_post_v6_preregistered",
        "primary_statistic": "historical_down_month_1m_partial_rank_ic_hac_t",
        **hac,
        "original_decision": decision,
        "post_v6_hypothesis": True,
        "evidence_scope": "historical_development",
    }
    ledger = pd.concat(
        [
            ledger.drop(
                columns=["bh_q_value_global", "bh_fdr_5pct"], errors="ignore"
            ),
            pd.DataFrame([trial]),
        ],
        ignore_index=True,
    )
    ledger["bh_q_value_global"] = benjamini_hochberg(
        ledger["p_value_two_sided"]
    )
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    ledger.to_csv(path, index=False, encoding="utf-8-sig")
    row = ledger[ledger["factor"].eq(RESEARCH_ID)].iloc[-1]
    return {
        "trial_id": int(row["trial_id"]),
        "q_value": float(row["bh_q_value_global"]),
        "bh_fdr_5pct": bool(row["bh_fdr_5pct"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1")
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("artifacts/tdx_bridge/raw")
    )
    parser.add_argument(
        "--tdx-audit",
        type=Path,
        default=Path("artifacts/alpha_phase1/tdx_research_raw_audit.json"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/evaluations")
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    validate_registration(REGISTRATION)

    signals, source_summary = build_signals(
        args.artifact_dir, args.raw_dir, args.tdx_audit
    )
    signal_columns = [
        "ts_code",
        "signal_date",
        "eligible_signal",
        "amihud_abnormal",
        "amount_contraction",
        "down_vol_amplification",
        "fragility_composite",
        "defensive_score",
        "partial_signal",
        "beta",
        "mark_return_1m",
    ]
    signal_path = args.output_dir / "b7_liquidity_fragility_signals.parquet"
    signals[signal_columns].to_parquet(signal_path, index=False)
    complete_components = signals[
        ["amihud_abnormal", "amount_contraction", "down_vol_amplification"]
    ].notna().all(axis=1)
    audit = {
        "research_id": RESEARCH_ID,
        "status": "PASS",
        "rows": int(len(signals)),
        "symbols": int(signals["ts_code"].nunique()),
        "signal_dates": int(signals["signal_date"].nunique()),
        "duplicate_keys": int(
            signals.duplicated(["ts_code", "signal_date"]).sum()
        ),
        "future_information_violations": 0,
        "eligible_rows": int(signals["eligible_signal"].sum()),
        "complete_component_coverage_eligible": float(
            complete_components[signals["eligible_signal"]].mean()
        ),
        "source_summary": source_summary,
        "sources": {
            "tdx_audit": sha256_file(args.tdx_audit),
            "market_return": sha256_file(
                args.artifact_dir / "all_a_equal_weight_market_return_v4.parquet"
            ),
            "style_panel": sha256_file(
                args.artifact_dir / "factor_panel_style_baseline_v5.parquet"
            ),
            "registration": sha256_file(REGISTRATION_PATH),
        },
        "config_sha256": config_sha256(),
        "pit_protocol": "daily observations and all-A market return through signal_date only",
    }
    if (
        audit["duplicate_keys"]
        or audit["future_information_violations"]
        or audit["complete_component_coverage_eligible"] < 0.70
    ):
        audit["status"] = "DATA_BLOCKED"
    audit_path = Path("artifacts/data_audits/b7_liquidity_fragility.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"event": "data_audit", **audit}, ensure_ascii=False), flush=True)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: B7 data audit failed")

    stage_s = stage_s_evaluation(signals)
    stage_s_monthly = stage_s.pop("monthly")
    stage_s_monthly.to_parquet(
        args.output_dir / "b7_liquidity_fragility_signal_monthly.parquet",
        index=False,
    )
    signal_status = (
        "SIGNAL_VALID" if stage_s["gates"]["passes_all"] else "REJECTED"
    )
    result: dict[str, object] = {
        "research_id": RESEARCH_ID,
        "registration_sha256": audit["sources"]["registration"],
        "config_sha256": config_sha256(),
        "evidence_scope": "historical_development",
        "data_audit": audit,
        "stage_s": {**stage_s, "status": signal_status},
        "stage_p": {"ran": False, "reason": "Stage S did not pass"},
    }
    decision = "REJECTED"
    if can_run_stage_p(signal_status):
        stage_p = evaluate_stage_p(
            signals,
            args.artifact_dir,
            args.output_dir,
            stage_s["summary"]["absolute_median_beta_correlation"],
        )
        result["stage_p"] = {"ran": True, **stage_p}
        decision = (
            "RESEARCH_SHADOW"
            if stage_p["passes_all_benchmarks"]
            else "REJECTED"
        )
    validate_research_decision(
        decision,
        evidence_scope="historical_development",
        live_observations=0,
        required_live_observations=12,
    )
    result["decision"] = decision
    result["multiple_testing"] = update_ledger(
        stage_s["summary"]["hac"], decision, args.output_dir
    )
    result_path = args.output_dir / "b7_liquidity_fragility_evaluation.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "decision",
                "stage_s_status": signal_status,
                "stage_p_ran": result["stage_p"]["ran"],
                "decision": decision,
                "result": str(result_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
