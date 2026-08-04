"""Run the preregistered Lane A shrunken-ICIR index-enhancement study."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import performance_metrics
from quant_trading_system.research.v6.incremental_evaluation import compare_portfolios
from quant_trading_system.research.v6.index_enhancement import build_shrunken_icir_scores
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.evaluate_capacity_v5 import summarize as summarize_capacity
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import BENCHMARKS, prepare_panel, run_one
from scripts.v6.update_multiple_testing_v6 import block_bootstrap_mean, hac_mean_test


VALIDATION_START = pd.Timestamp("2023-07-01")
VALIDATION_END = pd.Timestamp("2026-06-30")
RESEARCH_ID = "shrunken_icir_v6"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fixed_validation(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["signal_date"].between(VALIDATION_START, VALIDATION_END)]


def contribution_concentration(frame: pd.DataFrame) -> dict[str, object]:
    active = frame.assign(
        active_return=frame["portfolio_net_return"] - frame["benchmark_return"]
    )
    annual = active.groupby(active["signal_date"].dt.year)["active_return"].sum()
    total = float(annual.sum())
    maximum = float(annual.max()) if len(annual) else np.nan
    return {
        "annual_additive_active": {str(key): float(value) for key, value in annual.items()},
        "cumulative_additive_active": total,
        "maximum_positive_year_contribution_share": (
            maximum / total if total > 0 else None
        ),
    }


def industry_concentration(
    benchmark: str,
    holdings: pd.DataFrame,
    panel: pd.DataFrame,
    artifact_dir: Path,
) -> dict[str, object]:
    candidate = fixed_validation(holdings[holdings["index_code"].eq(benchmark)])
    weights = pd.read_parquet(
        artifact_dir / "tushare" / f"index_weight_{benchmark.replace('.', '_')}.parquet"
    )
    weights["signal_date"] = pd.to_datetime(weights["trade_date"], format="%Y%m%d")
    weights = fixed_validation(
        weights.rename(columns={"con_code": "ts_code", "weight": "benchmark_weight"})
    )
    weights["benchmark_weight"] = weights["benchmark_weight"] / 100.0
    keys = ["signal_date", "ts_code"]
    merged = candidate[keys + ["weight"]].merge(
        weights[keys + ["benchmark_weight"]], on=keys, how="outer"
    ).fillna({"weight": 0.0, "benchmark_weight": 0.0})
    features = panel[keys + ["l1_code", "mark_return_1m"]].drop_duplicates(keys)
    merged = merged.merge(features, on=keys, how="left", validate="many_to_one")
    merged["active_contribution"] = (
        merged["weight"] - merged["benchmark_weight"]
    ) * merged["mark_return_1m"].fillna(-1.0)
    industry = merged.groupby("l1_code", dropna=False)["active_contribution"].sum()
    total = float(industry.sum())
    maximum = float(industry.max()) if len(industry) else np.nan
    return {
        "additive_active_by_industry": {
            str(key): float(value) for key, value in industry.sort_values(ascending=False).items()
        },
        "reconstructed_cumulative_active": total,
        "maximum_positive_industry_contribution_share": (
            maximum / total if total > 0 else None
        ),
        "rows_missing_industry": int(merged["l1_code"].isna().sum()),
        "rows_missing_return": int(merged["mark_return_1m"].isna().sum()),
    }


def update_ledger(
    *,
    candidate: pd.DataFrame,
    baseline: pd.DataFrame,
    decision: str,
    output_dir: Path,
) -> dict[str, object]:
    keys = ["index_code", "signal_date"]
    merged = fixed_validation(baseline).merge(
        fixed_validation(candidate), on=keys, suffixes=("_base", "_candidate")
    )
    merged["improvement"] = (
        merged["portfolio_net_return_candidate"] - merged["portfolio_net_return_base"]
    )
    monthly = merged.groupby("signal_date", sort=True)["improvement"].mean()
    test = hac_mean_test(monthly)
    bootstrap = block_bootstrap_mean(monthly, seed=7)
    ledger_path = output_dir / "multiple_testing_ledger_v6.csv"
    ledger = pd.read_csv(ledger_path)
    ledger = ledger[ledger["factor"].ne(RESEARCH_ID)].copy()
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": RESEARCH_ID,
        "family": "index_enhancement_shrunken_icir",
        "research_version": "V6_preregistered",
        "primary_statistic": "fixed_validation_monthly_net_return_delta_vs_24m_hac_t",
        **test,
        "original_decision": decision,
    }
    ledger = pd.concat(
        [
            ledger.drop(columns=["bh_q_value_global", "bh_fdr_5pct"], errors="ignore"),
            pd.DataFrame([trial]),
        ],
        ignore_index=True,
    )
    ledger["bh_q_value_global"] = benjamini_hochberg(ledger["p_value_two_sided"])
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    return {
        "trial": trial,
        "q_value": float(ledger.iloc[-1]["bh_q_value_global"]),
        "bh_fdr_5pct": bool(ledger.iloc[-1]["bh_fdr_5pct"]),
        "block_bootstrap": bootstrap,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluations"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    panel = prepare_panel(args.artifact_dir)
    panel, weight_audit = build_shrunken_icir_scores(panel)
    weight_path = args.output_dir / f"{RESEARCH_ID}_weights.parquet"
    weight_audit.to_parquet(weight_path, index=False)
    data_audit = {
        "version": 6,
        "research_id": RESEARCH_ID,
        "status": "PASS",
        "rows": int(len(panel)),
        "symbols": int(panel["ts_code"].nunique()),
        "signal_dates": int(panel["signal_date"].nunique()),
        "date_start": panel["signal_date"].min().date().isoformat(),
        "date_end": panel["signal_date"].max().date().isoformat(),
        "duplicate_keys": int(panel.duplicated(["ts_code", "signal_date"]).sum()),
        "score_coverage": float(panel["shrunken_icir_v6_score"].notna().mean()),
        "weight_months": int(len(weight_audit)),
        "weight_sum_max_error": float(
            (
                weight_audit.filter(like="weight_").sum(axis=1) - 1.0
            ).abs().max()
        ),
        "future_information_violations": int(
            (
                weight_audit["latest_used_exit_date"].notna()
                & weight_audit["latest_used_exit_date"].gt(weight_audit["signal_date"])
            ).sum()
        ),
        "sources": {
            "style_panel": sha256_file(args.artifact_dir / "factor_panel_style_baseline_v5.parquet"),
            "execution_labels": sha256_file(args.artifact_dir / "portfolio_execution_labels_v5.parquet"),
            "registration": sha256_file(Path("artifacts/registrations/shrunken_icir_v6.md")),
        },
    }
    if data_audit["duplicate_keys"] or data_audit["future_information_violations"]:
        data_audit["status"] = "DATA_BLOCKED"
    audit_path = Path("artifacts/data_audits/shrunken_icir_v6.json")
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(data_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "data_audit", **data_audit}, ensure_ascii=False), flush=True)
    if data_audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: shrunken ICIR audit failed")

    monthly_parts: list[pd.DataFrame] = []
    holdings_parts: list[pd.DataFrame] = []
    construction: dict[str, object] = {}
    for benchmark in BENCHMARKS:
        monthly, holdings, report = run_one(
            benchmark,
            panel,
            args.artifact_dir,
            0.20,
            "shrunken_icir_v6_score",
            "expanding_ICIR_shrunk_to_equal_with_60_prior_months",
        )
        monthly_parts.append(monthly)
        holdings_parts.append(holdings)
        construction[benchmark] = report
    monthly = pd.concat(monthly_parts, ignore_index=True)
    holdings = pd.concat(holdings_parts, ignore_index=True)
    monthly.to_parquet(args.output_dir / f"{RESEARCH_ID}_monthly.parquet", index=False)
    holdings.to_parquet(args.output_dir / f"{RESEARCH_ID}_holdings.parquet", index=False)

    baseline_stems = {
        "equal_style_p0": "style_baseline_portfolio_v5",
        "historical_icir": "style_historical_icir_portfolio_v5",
        "rolling_regression_24m": "style_rolling_regression_24m_portfolio_v5",
    }
    comparisons: dict[str, object] = {}
    validation_candidate = fixed_validation(monthly)
    validation_holdings = fixed_validation(holdings)
    for name, stem in baseline_stems.items():
        comparisons[name] = compare_portfolios(
            fixed_validation(pd.read_parquet(args.artifact_dir / f"{stem}_monthly.parquet")),
            validation_candidate,
            baseline_holdings=fixed_validation(
                pd.read_parquet(args.artifact_dir / f"{stem}_holdings.parquet")
            ),
            candidate_holdings=validation_holdings,
        )

    adv = pd.read_parquet(args.artifact_dir / "adv20_capacity_v5.parquet")
    capacity_frame = holdings.merge(
        adv, on=["ts_code", "signal_date"], how="left", validate="many_to_one"
    )
    promotion: dict[str, object] = {}
    diagnostics: dict[str, object] = {}
    primary = comparisons["rolling_regression_24m"]["benchmarks"]
    for benchmark in BENCHMARKS:
        candidate = validation_candidate[validation_candidate["index_code"].eq(benchmark)]
        metrics = performance_metrics(candidate)
        report = construction[benchmark]
        capacity = summarize_capacity(
            fixed_validation(capacity_frame[capacity_frame["index_code"].eq(benchmark)]),
            10_000_000,
            0.05,
        )
        annual = contribution_concentration(candidate)
        industry = industry_concentration(
            benchmark, validation_holdings, panel, args.artifact_dir
        )
        violations = {
            "stock_above_8pct": int(candidate["maximum_stock_weight"].gt(0.08 + 1e-10).sum()),
            "industry_above_30pct": int(candidate["maximum_industry_weight"].gt(0.30 + 1e-10).sum()),
            "size_outside_025": int(candidate["size_active_exposure"].abs().gt(0.25 + 1e-10).sum()),
            "turnover_above_100pct": int(candidate["turnover"].gt(1.0 + 1e-10).sum()),
            "missing_holding_return": int(candidate["missing_return_weight"].gt(0).sum()),
        }
        delta = primary[benchmark]["delta"]
        gates = {
            "annual_net_excess_gt_002": metrics["annual_excess_return_difference"] > 0.02,
            "information_ratio_gt_075": metrics["information_ratio"] > 0.75,
            "tracking_error_at_most_005": metrics["tracking_error"] <= 0.05,
            "cost_stress_20bp_positive": report["fixed_validation_cost_stress"]["0.002"]["annual_excess_return_difference"] > 0,
            "capacity_10m_pass": (
                capacity["trades_missing_adv20"] == 0
                and capacity["trades_above_participation_cap"] == 0
                and capacity["minimum_capacity_at_cap_cny"] >= 10_000_000 - 1e-6
            ),
            "constraints_pass": not any(violations.values()),
            "year_contribution_at_most_050": (
                annual["maximum_positive_year_contribution_share"] is not None
                and annual["maximum_positive_year_contribution_share"] <= 0.50
            ),
            "industry_contribution_at_most_035": (
                industry["maximum_positive_industry_contribution_share"] is not None
                and industry["maximum_positive_industry_contribution_share"] <= 0.35
            ),
            "delta_net_excess_vs_24m_positive": delta["annual_excess_return_difference"] > 0,
            "delta_ir_vs_24m_positive": delta["information_ratio"] > 0,
        }
        gates["passes_all_registered_gates"] = all(gates.values())
        promotion[benchmark] = gates
        diagnostics[benchmark] = {
            "metrics": metrics,
            "capacity": capacity,
            "annual_concentration": annual,
            "industry_concentration": industry,
            "constraint_violations": violations,
        }

    decision = (
        "PROMOTE_TO_LIVE_SHADOW"
        if all(item["passes_all_registered_gates"] for item in promotion.values())
        else "REJECTED"
    )
    primary_monthly = pd.read_parquet(
        args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"
    )
    multiple_testing = update_ledger(
        candidate=monthly,
        baseline=primary_monthly,
        decision=decision,
        output_dir=args.output_dir,
    )
    result = {
        "research_id": RESEARCH_ID,
        "registration_sha256": sha256_file(Path("artifacts/registrations/shrunken_icir_v6.md")),
        "data_audit": data_audit,
        "construction_reports": construction,
        "comparisons": comparisons,
        "diagnostics": diagnostics,
        "promotion": promotion,
        "multiple_testing": multiple_testing,
        "decision": decision,
    }
    result_path = args.output_dir / f"{RESEARCH_ID}_evaluation.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "decision", "decision": decision, "promotion": promotion}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
