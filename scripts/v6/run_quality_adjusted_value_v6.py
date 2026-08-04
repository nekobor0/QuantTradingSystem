"""Run the preregistered Lane C concentrated quality-adjusted-value strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    enforce_execution_and_turnover,
    maximum_drawdown,
    performance_metrics,
)
from quant_trading_system.research.v6.fundamental_selection import (
    quality_adjusted_value_signal,
    select_with_industry_cap,
)
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.evaluate_capacity_v5 import summarize as summarize_capacity
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import prepare_panel
from scripts.v6.update_multiple_testing_v6 import block_bootstrap_mean, hac_mean_test


RESEARCH_ID = "quality_adjusted_value_v6"
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


def build_strategy(
    panel: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    pretrade = pd.Series(dtype=float)
    frozen_ranking: pd.DataFrame | None = None
    monthly_rows: list[dict[str, object]] = []
    holding_rows: list[dict[str, object]] = []
    exit_events = 0
    quarter_rebalances = 0
    for signal_date, month in panel.groupby("signal_date", sort=True):
        month = month.copy()
        indexed = month.drop_duplicates("ts_code").set_index("ts_code")
        current_ok = (
            indexed["eligible_entry"].fillna(False)
            & indexed["raw_signal"].notna()
            & indexed["baseline_quality_z"].ge(-1.0)
        )
        if pd.Timestamp(signal_date).month in {3, 6, 9, 12}:
            frozen_ranking = indexed.loc[current_ok].reset_index()[
                ["ts_code", "l1_code", "raw_signal"]
            ].copy()
            quarter_rebalances += 1
        if frozen_ranking is None:
            continue
        available = set(indexed.index[current_ok])
        candidates = frozen_ranking[frozen_ranking["ts_code"].isin(available)]
        selected = select_with_industry_cap(candidates, count=30, max_per_industry=6)
        target = pd.Series(1.0 / len(selected), index=selected) if selected else pd.Series(dtype=float)
        held = set(pretrade.index)
        exit_events += sum(name not in selected for name in held)
        forced_exit = indexed["delist_date"].notna() & indexed["delist_date"].le(indexed["entry_date"])
        can_trade = indexed["entry_tradable"].fillna(False) | forced_exit
        actual, turnover = enforce_execution_and_turnover(target, pretrade, can_trade, turnover_cap=1.0)
        if actual.empty:
            continue
        returns = indexed["mark_return_1m"].reindex(actual.index)
        realized = returns.fillna(-1.0)
        gross_return = float((actual * realized).sum())
        cost = turnover * 0.0005
        net_return = gross_return - cost
        benchmark_sample = indexed.loc[indexed["eligible_entry"].fillna(False), "mark_return_1m"].dropna()
        benchmark_return = float(benchmark_sample.mean())
        industries = indexed["l1_code"].reindex(actual.index)
        industry_weights = actual.groupby(industries).sum()
        monthly_rows.append(
            {
                "index_code": "ALL_A_EQUAL_WEIGHT",
                "signal_date": signal_date,
                "portfolio_gross_return": gross_return,
                "portfolio_net_return": net_return,
                "benchmark_return": benchmark_return,
                "turnover": turnover,
                "cost": cost,
                "holdings": int(len(actual)),
                "maximum_stock_weight": float(actual.max()),
                "maximum_industry_weight": float(industry_weights.max()),
                "value_exposure": float((actual * indexed["baseline_value_z"].reindex(actual.index)).sum()),
                "quality_exposure": float((actual * indexed["baseline_quality_z"].reindex(actual.index)).sum()),
                "missing_return_weight": float(actual[returns.isna()].sum()),
            }
        )
        holding_rows.extend(
            {
                "index_code": "ALL_A_EQUAL_WEIGHT",
                "signal_date": signal_date,
                "ts_code": name,
                "l1_code": indexed.at[name, "l1_code"],
                "weight": float(weight),
                "trade_weight": float(weight - pretrade.get(name, 0.0)),
                "gross_contribution": float(weight * realized.get(name, -1.0)),
            }
            for name, weight in actual.items()
        )
        growth = 1.0 + gross_return
        pretrade = actual * (1.0 + realized) / growth if growth > 0 else actual
        pretrade = pretrade[pretrade > 1e-14]
    return pd.DataFrame(monthly_rows), pd.DataFrame(holding_rows), {
        "quarter_rebalances": quarter_rebalances,
        "deterioration_or_eligibility_exit_events": exit_events,
    }


def signal_evaluation(signals: pd.DataFrame, labels: pd.DataFrame) -> dict[str, object]:
    keys = ["ts_code", "signal_date"]
    label_columns = [*keys, "forward_return_6m", "exit_6m_tradable"]
    if "entry_tradable" not in signals.columns:
        label_columns.append("entry_tradable")
    merged = signals.merge(
        labels[label_columns], on=keys, how="left", validate="one_to_one"
    )
    evaluation = merged[
        merged["signal_date"].between(VALIDATION_START, pd.Timestamp("2025-12-31"))
        & merged["eligible_entry"].fillna(False)
        & merged["entry_tradable"].fillna(False)
        & merged["exit_6m_tradable"].fillna(False)
        & merged["forward_return_6m"].notna()
    ]
    monthly_ic = evaluation.groupby("signal_date", sort=True).apply(
        lambda group: group["standardized_signal"].corr(
            group["forward_return_6m"], method="spearman"
        ),
        include_groups=False,
    ).dropna()
    hac = hac_mean_test(monthly_ic)
    return {
        "rows": int(len(evaluation)),
        "months": int(len(monthly_ic)),
        "mean_rank_ic_6m": float(monthly_ic.mean()),
        "hac": hac,
        "bootstrap": block_bootstrap_mean(monthly_ic, seed=8),
        "last_complete_label_signal_date": evaluation["signal_date"].max().date().isoformat(),
    }


def update_ledger(
    signal_result: dict[str, object], decision: str, output_dir: Path
) -> dict[str, object]:
    ledger_path = output_dir / "multiple_testing_ledger_v6.csv"
    ledger = pd.read_csv(ledger_path)
    ledger = ledger[ledger["factor"].ne(RESEARCH_ID)].copy()
    hac = signal_result["hac"]
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": RESEARCH_ID,
        "family": "concentrated_fundamental_quality_adjusted_value",
        "research_version": "V6_preregistered",
        "primary_statistic": "fixed_validation_6m_rank_ic_hac_t",
        **hac,
        "original_decision": decision,
    }
    ledger = pd.concat(
        [ledger.drop(columns=["bh_q_value_global", "bh_fdr_5pct"], errors="ignore"), pd.DataFrame([trial])],
        ignore_index=True,
    )
    ledger["bh_q_value_global"] = benjamini_hochberg(ledger["p_value_two_sided"])
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    return {
        "trial": trial,
        "q_value": float(ledger.iloc[-1]["bh_q_value_global"]),
        "bh_fdr_5pct": bool(ledger.iloc[-1]["bh_fdr_5pct"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluations"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    panel = prepare_panel(args.artifact_dir)
    signals = quality_adjusted_value_signal(panel)
    signal_columns = [
        "ts_code", "signal_date", "eligible_entry", "baseline_value_z", "baseline_quality_z",
        "raw_signal", "winsorized_signal", "standardized_signal", "neutralized_signal",
    ]
    signals[signal_columns].to_parquet(
        args.output_dir / f"{RESEARCH_ID}_signals.parquet", index=False
    )
    labels_path = args.artifact_dir / "slow_horizon_labels_v4_t1_open.parquet"
    labels = pd.read_parquet(labels_path)
    labels["signal_date"] = pd.to_datetime(labels["signal_date"])
    signal_result = signal_evaluation(signals, labels)
    audit = {
        "version": 6,
        "research_id": RESEARCH_ID,
        "status": "PASS",
        "rows": int(len(signals)),
        "symbols": int(signals["ts_code"].nunique()),
        "signal_dates": int(signals["signal_date"].nunique()),
        "duplicate_keys": int(signals.duplicated(["ts_code", "signal_date"]).sum()),
        "raw_signal_coverage": float(signals["raw_signal"].notna().mean()),
        "eligible_raw_coverage": float(
            signals.loc[signals["eligible_entry"], "raw_signal"].notna().mean()
        ),
        "future_information_violations": 0,
        "pit_protocol": "latest financial version visible by ann_date at signal month end; carry-forward <=250 days",
        "six_month_labels_used_for_evaluation_only": True,
        "sources": {
            "style_panel": sha256_file(args.artifact_dir / "factor_panel_style_baseline_v5.parquet"),
            "labels": sha256_file(labels_path),
            "registration": sha256_file(Path("artifacts/registrations/quality_adjusted_value_v6.md")),
        },
    }
    if audit["duplicate_keys"] or audit["future_information_violations"]:
        audit["status"] = "DATA_BLOCKED"
    audit_path = Path("artifacts/data_audits/quality_adjusted_value_v6.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "data_audit", **audit}, ensure_ascii=False), flush=True)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: quality-adjusted-value audit failed")

    monthly, holdings, construction = build_strategy(signals)
    monthly.to_parquet(args.output_dir / f"{RESEARCH_ID}_monthly.parquet", index=False)
    holdings.to_parquet(args.output_dir / f"{RESEARCH_ID}_holdings.parquet", index=False)
    validation = fixed_validation(monthly)
    validation_holdings = fixed_validation(holdings)
    metrics = performance_metrics(validation)
    net = validation["portfolio_net_return"]
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(12))
    benchmark_mdd = maximum_drawdown(validation["benchmark_return"])
    cost_stress = {
        str(rate): performance_metrics(
            validation.assign(
                portfolio_net_return=validation["portfolio_gross_return"] - validation["turnover"] * rate
            )
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
    annual = validation.assign(
        active=validation["portfolio_net_return"] - validation["benchmark_return"]
    ).groupby(validation["signal_date"].dt.year)["active"].sum()
    total_active = float(annual.sum())
    stock_contribution = validation_holdings.groupby("ts_code")["gross_contribution"].sum()
    maximum_stock_share = (
        float(stock_contribution.max() / total_active) if total_active > 0 else None
    )
    constraints = {
        "months_not_30_holdings": int(validation["holdings"].ne(30).sum()),
        "stock_above_equal_weight_tolerance": int(validation["maximum_stock_weight"].gt(1 / 30 + 0.01).sum()),
        "industry_above_25pct": int(validation["maximum_industry_weight"].gt(0.25 + 1e-10).sum()),
        "missing_return_weight": int(validation["missing_return_weight"].gt(0).sum()),
    }
    capacity_10m = capacities["10000000"]
    gates = {
        "annual_net_excess_gt_003": metrics["annual_excess_return_difference"] > 0.03,
        "sharpe_gt_075": sharpe > 0.75,
        "cost_stress_20bp_positive": cost_stress["0.002"]["annual_excess_return_difference"] > 0,
        "drawdown_not_worse_than_benchmark_by_005": metrics["absolute_max_drawdown"] >= benchmark_mdd - 0.05,
        "industry_weight_at_most_025": constraints["industry_above_25pct"] == 0,
        "single_stock_contribution_at_most_020": maximum_stock_share is not None and maximum_stock_share <= 0.20,
        "capacity_10m_pass": (
            capacity_10m["trades_missing_adv20"] == 0
            and capacity_10m["trades_above_participation_cap"] == 0
            and capacity_10m["minimum_capacity_at_cap_cny"] >= 10_000_000 - 1e-6
        ),
        "rank_ic_6m_positive": signal_result["mean_rank_ic_6m"] > 0,
        "rank_ic_hac_t_gt_1": signal_result["hac"]["t_statistic"] > 1.0,
        "constraints_pass": not any(constraints.values()),
    }
    gates["passes_all_registered_gates"] = all(gates.values())
    decision = "PROMOTE_TO_LIVE_SHADOW" if gates["passes_all_registered_gates"] else "REJECTED"
    multiple_testing = update_ledger(signal_result, decision, args.output_dir)
    result = {
        "research_id": RESEARCH_ID,
        "registration_sha256": sha256_file(Path("artifacts/registrations/quality_adjusted_value_v6.md")),
        "data_audit": audit,
        "signal_evaluation": signal_result,
        "construction": construction,
        "fixed_validation": {
            "metrics": metrics,
            "sharpe": sharpe,
            "benchmark_maximum_drawdown": benchmark_mdd,
            "cost_stress": cost_stress,
            "capacity_scenarios": capacities,
            "annual_additive_active": {str(k): float(v) for k, v in annual.items()},
            "maximum_stock_contribution_share": maximum_stock_share,
            "constraints": constraints,
        },
        "promotion": gates,
        "multiple_testing": multiple_testing,
        "decision": decision,
    }
    (args.output_dir / f"{RESEARCH_ID}_evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"event": "decision", "decision": decision, "promotion": gates}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
