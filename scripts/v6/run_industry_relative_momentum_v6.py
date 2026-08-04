"""Run the preregistered Lane F industry-relative momentum allocation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    enforce_execution_and_turnover,
    performance_metrics,
)
from quant_trading_system.research.v6.industry_rotation import build_industry_momentum_scores
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.evaluate_capacity_v5 import summarize as summarize_capacity
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import prepare_panel
from scripts.v6.update_multiple_testing_v6 import block_bootstrap_mean, hac_mean_test


RESEARCH_ID = "industry_relative_momentum_v6"
VALIDATION_START = pd.Timestamp("2023-07-01")
VALIDATION_END = pd.Timestamp("2026-06-30")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fixed_validation(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["signal_date"].between(VALIDATION_START, VALIDATION_END)]


def industry_return_panel(panel: pd.DataFrame) -> pd.DataFrame:
    valid = panel[
        panel["eligible_entry"].fillna(False)
        & panel["l1_code"].notna()
        & panel["mark_return_1m"].notna()
    ]
    return (
        valid.groupby(["signal_date", "l1_code"], as_index=False)
        .agg(
            industry_return=("mark_return_1m", "mean"),
            exit_date=("exit_date", "max"),
            member_count=("ts_code", "nunique"),
        )
    )


def build_strategy(
    panel: pd.DataFrame, scores: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    score_map = {
        pd.Timestamp(date): group.set_index("l1_code")["relative_momentum"]
        for date, group in scores.groupby("signal_date")
    }
    pretrade = pd.Series(dtype=float)
    monthly_rows: list[dict[str, object]] = []
    holding_rows: list[dict[str, object]] = []
    for signal_date, month in panel.groupby("signal_date", sort=True):
        industry_scores = score_map.get(pd.Timestamp(signal_date))
        if industry_scores is None or len(industry_scores) < 5:
            continue
        indexed = month.drop_duplicates("ts_code").set_index("ts_code")
        eligible = indexed[
            indexed["eligible_entry"].fillna(False) & indexed["l1_code"].notna()
        ]
        industries = sorted(set(eligible["l1_code"]).intersection(industry_scores.index))
        if len(industries) < 5:
            continue
        selected_industries = list(industry_scores.reindex(industries).nlargest(5).index)
        target_parts = []
        benchmark_parts = []
        for industry in industries:
            names = eligible.index[eligible["l1_code"].eq(industry)]
            benchmark_parts.append(pd.Series(1.0 / len(industries) / len(names), index=names))
            if industry in selected_industries:
                target_parts.append(pd.Series(0.20 / len(names), index=names))
        target = pd.concat(target_parts).groupby(level=0).sum()
        benchmark_weights = pd.concat(benchmark_parts).groupby(level=0).sum()
        forced_exit = indexed["delist_date"].notna() & indexed["delist_date"].le(indexed["entry_date"])
        can_trade = indexed["entry_tradable"].fillna(False) | forced_exit
        actual, turnover = enforce_execution_and_turnover(target, pretrade, can_trade, turnover_cap=1.0)
        returns = indexed["mark_return_1m"]
        realized = returns.reindex(actual.index).fillna(-1.0)
        gross = float((actual * realized).sum())
        net = gross - turnover * 0.0005
        benchmark = float((benchmark_weights * returns.reindex(benchmark_weights.index).fillna(-1.0)).sum())
        actual_industry = actual.groupby(indexed["l1_code"].reindex(actual.index)).sum()
        monthly_rows.append(
            {
                "index_code": "EQUAL_WEIGHT_INDUSTRIES",
                "signal_date": signal_date,
                "portfolio_gross_return": gross,
                "portfolio_net_return": net,
                "benchmark_return": benchmark,
                "turnover": turnover,
                "cost": turnover * 0.0005,
                "holdings": int(len(actual)),
                "selected_industries": len(selected_industries),
                "maximum_industry_weight": float(actual_industry.max()),
                "maximum_stock_weight": float(actual.max()),
                "missing_return_weight": float(actual[returns.reindex(actual.index).isna()].sum()),
            }
        )
        holding_rows.extend(
            {
                "index_code": "EQUAL_WEIGHT_INDUSTRIES",
                "signal_date": signal_date,
                "ts_code": name,
                "l1_code": indexed.at[name, "l1_code"],
                "weight": float(weight),
                "trade_weight": float(weight - pretrade.get(name, 0.0)),
            }
            for name, weight in actual.items()
        )
        growth = 1.0 + gross
        pretrade = actual * (1.0 + realized) / growth if growth > 0 else actual
        pretrade = pretrade[pretrade > 1e-14]
    return pd.DataFrame(monthly_rows), pd.DataFrame(holding_rows)


def signal_evaluation(scores: pd.DataFrame, returns: pd.DataFrame) -> dict[str, object]:
    merged = scores.merge(
        returns[["signal_date", "l1_code", "industry_return"]],
        on=["signal_date", "l1_code"],
        how="inner",
        validate="one_to_one",
    )
    valid = fixed_validation(merged)
    monthly_ic = valid.groupby("signal_date", sort=True).apply(
        lambda group: group["relative_momentum"].corr(group["industry_return"], method="spearman"),
        include_groups=False,
    ).dropna()
    return {
        "rows": int(len(valid)),
        "months": int(len(monthly_ic)),
        "mean_rank_ic_1m": float(monthly_ic.mean()),
        "hac": hac_mean_test(monthly_ic),
        "bootstrap": block_bootstrap_mean(monthly_ic, seed=11),
    }


def marginal_overlay(candidate: pd.DataFrame, artifact_dir: Path) -> dict[str, object]:
    active = fixed_validation(candidate).set_index("signal_date")
    active_return = active["portfolio_net_return"] - active["benchmark_return"]
    base = fixed_validation(
        pd.read_parquet(artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet")
    )
    result: dict[str, object] = {}
    for benchmark, frame in base.groupby("index_code"):
        ordered = frame.sort_values("signal_date").copy()
        overlay = active_return.reindex(ordered["signal_date"]).to_numpy()
        blended = ordered.copy()
        blended["portfolio_net_return"] = blended["portfolio_net_return"] + 0.20 * overlay
        baseline_metrics = performance_metrics(ordered)
        blended_metrics = performance_metrics(blended)
        result[str(benchmark)] = {
            "baseline": baseline_metrics,
            "blended": blended_metrics,
            "delta_ir": float(blended_metrics["information_ratio"] - baseline_metrics["information_ratio"]),
            "delta_net_excess": float(blended_metrics["annual_excess_return_difference"] - baseline_metrics["annual_excess_return_difference"]),
        }
    return result


def update_ledger(signal_result: dict[str, object], decision: str, output_dir: Path) -> dict[str, object]:
    ledger_path = output_dir / "multiple_testing_ledger_v6.csv"
    ledger = pd.read_csv(ledger_path)
    ledger = ledger[ledger["factor"].ne(RESEARCH_ID)].copy()
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": RESEARCH_ID,
        "family": "industry_rotation_relative_momentum",
        "research_version": "V6_preregistered",
        "primary_statistic": "fixed_validation_1m_industry_rank_ic_hac_t",
        **signal_result["hac"],
        "original_decision": decision,
    }
    ledger = pd.concat(
        [ledger.drop(columns=["bh_q_value_global", "bh_fdr_5pct"], errors="ignore"), pd.DataFrame([trial])],
        ignore_index=True,
    )
    ledger["bh_q_value_global"] = benjamini_hochberg(ledger["p_value_two_sided"])
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    return {"trial": trial, "q_value": float(ledger.iloc[-1]["bh_q_value_global"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluations"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    panel = prepare_panel(args.artifact_dir)
    industry_returns = industry_return_panel(panel)
    scores, score_audit = build_industry_momentum_scores(industry_returns, history_months=11)
    scores.to_parquet(args.output_dir / f"{RESEARCH_ID}_signals.parquet", index=False)
    score_audit.to_parquet(args.output_dir / f"{RESEARCH_ID}_signal_audit.parquet", index=False)
    audit = {
        "version": 6,
        "research_id": RESEARCH_ID,
        "status": "PASS",
        "industry_return_rows": int(len(industry_returns)),
        "score_rows": int(len(scores)),
        "signal_dates": int(scores["signal_date"].nunique()),
        "industries": int(scores["l1_code"].nunique()),
        "duplicate_keys": int(scores.duplicated(["signal_date", "l1_code"]).sum()),
        "future_information_violations": int(score_audit["latest_used_exit_date"].gt(score_audit["signal_date"]).sum()),
        "history_months": 11,
        "sources": {
            "style_panel": sha256_file(args.artifact_dir / "factor_panel_style_baseline_v5.parquet"),
            "execution_labels": sha256_file(args.artifact_dir / "portfolio_execution_labels_v5.parquet"),
            "registration": sha256_file(Path("artifacts/registrations/industry_relative_momentum_v6.md")),
        },
    }
    if audit["duplicate_keys"] or audit["future_information_violations"]:
        audit["status"] = "DATA_BLOCKED"
    Path("artifacts/data_audits/industry_relative_momentum_v6.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"event": "data_audit", **audit}, ensure_ascii=False), flush=True)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: industry momentum audit failed")
    signal_result = signal_evaluation(scores, industry_returns)
    monthly, holdings = build_strategy(panel, scores)
    monthly.to_parquet(args.output_dir / f"{RESEARCH_ID}_monthly.parquet", index=False)
    holdings.to_parquet(args.output_dir / f"{RESEARCH_ID}_holdings.parquet", index=False)
    validation = fixed_validation(monthly)
    validation_holdings = fixed_validation(holdings)
    metrics = performance_metrics(validation)
    cost_stress = {
        str(rate): performance_metrics(
            validation.assign(portfolio_net_return=validation["portfolio_gross_return"] - validation["turnover"] * rate)
        )
        for rate in (0.0005, 0.001, 0.002)
    }
    adv = pd.read_parquet(args.artifact_dir / "adv20_capacity_v5.parquet")
    capacity_frame = validation_holdings.merge(
        adv, on=["ts_code", "signal_date"], how="left", validate="many_to_one"
    )
    capacities = {
        str(capital): summarize_capacity(capacity_frame, capital, 0.05)
        for capital in (1_000_000, 5_000_000, 10_000_000)
    }
    active = validation["portfolio_net_return"] - validation["benchmark_return"]
    rolling_vol = validation["benchmark_return"].rolling(6, min_periods=3).std()
    vol_median = float(rolling_vol.median())
    regimes = {
        "up_market_mean_active": float(active[validation["benchmark_return"].ge(0)].mean()),
        "down_market_mean_active": float(active[validation["benchmark_return"].lt(0)].mean()),
        "high_vol_mean_active": float(active[rolling_vol.ge(vol_median)].mean()),
        "low_vol_mean_active": float(active[rolling_vol.lt(vol_median)].mean()),
        "industry_hit_rate": float(active.gt(0).mean()),
    }
    marginal = marginal_overlay(monthly, args.artifact_dir)
    capacity_10m = capacities["10000000"]
    constraints = {
        "selected_industries_not_5": int(validation["selected_industries"].ne(5).sum()),
        "industry_above_25pct": int(validation["maximum_industry_weight"].gt(0.25 + 1e-10).sum()),
        "missing_return_weight": int(validation["missing_return_weight"].gt(0).sum()),
    }
    gates = {
        "annual_net_excess_gt_003": metrics["annual_excess_return_difference"] > 0.03,
        "information_ratio_gt_050": metrics["information_ratio"] > 0.50,
        "rank_ic_1m_positive": signal_result["mean_rank_ic_1m"] > 0,
        "rank_ic_hac_t_gt_1": signal_result["hac"]["t_statistic"] > 1.0,
        "cost_stress_20bp_positive": cost_stress["0.002"]["annual_excess_return_difference"] > 0,
        "active_max_drawdown_gt_minus_010": metrics["excess_max_drawdown"] > -0.10,
        "average_turnover_lt_050": metrics["average_monthly_one_way_turnover"] < 0.50,
        "industry_weight_at_most_025": constraints["industry_above_25pct"] == 0,
        "capacity_10m_pass": (
            capacity_10m["trades_missing_adv20"] == 0
            and capacity_10m["trades_above_participation_cap"] == 0
            and capacity_10m["minimum_capacity_at_cap_cny"] >= 10_000_000 - 1e-6
        ),
        "delta_ir_positive_both_index_baselines": all(item["delta_ir"] > 0 for item in marginal.values()),
        "constraints_pass": not any(constraints.values()),
    }
    gates["passes_all_registered_gates"] = all(gates.values())
    decision = "PROMOTE_TO_LIVE_SHADOW" if gates["passes_all_registered_gates"] else "REJECTED"
    ledger = update_ledger(signal_result, decision, args.output_dir)
    result = {
        "research_id": RESEARCH_ID,
        "registration_sha256": sha256_file(Path("artifacts/registrations/industry_relative_momentum_v6.md")),
        "data_audit": audit,
        "signal_evaluation": signal_result,
        "fixed_validation": {
            "metrics": metrics,
            "cost_stress": cost_stress,
            "capacity_scenarios": capacities,
            "regimes": regimes,
            "constraints": constraints,
        },
        "marginal_overlay": marginal,
        "promotion": gates,
        "multiple_testing": ledger,
        "decision": decision,
    }
    (args.output_dir / f"{RESEARCH_ID}_evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"event": "decision", "decision": decision, "promotion": gates}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
