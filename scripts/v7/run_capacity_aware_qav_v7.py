"""Run the preregistered C7 capacity-aware Quality-adjusted Value study."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    enforce_execution_and_turnover,
    maximum_drawdown,
    performance_metrics,
)
from quant_trading_system.research.v7.capacity_aware_qav import (
    add_capacity_aware_signals,
    constrained_rank_target,
    effective_days_last_60,
    monthly_signal_diagnostics,
    square_root_impact_cost,
)
from quant_trading_system.research.v7.governance import (
    can_run_stage_p,
    validate_registration,
    validate_research_decision,
)
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import prepare_panel
from scripts.v6.update_multiple_testing_v6 import hac_mean_test


RESEARCH_ID = "C7_CAPACITY_AWARE_QAV"
REGISTRATION_PATH = Path("artifacts/registrations/c7_capacity_aware_qav.md")
CAPITAL_CNY = 10_000_000.0
ADV_CAP = 0.02
STOCK_CAP = 0.02
INDUSTRY_ACTIVE_CAP = 0.05
EFFECTIVE_DAYS_MINIMUM = 40

REGISTRATION = {
    "research_id": RESEARCH_ID,
    "post_v6_hypothesis": True,
    "core_horizon": "6m",
    "primary_benchmark": "ALL_A_EQUAL_WEIGHT",
    "role": "SLEEVE_ALPHA",
    "variant_count": 1,
    "historical_evidence_use": "development_only",
    "live_confirmation": {"unit": "months", "minimum": 12},
    "relaxations": {
        "core_capacity": [
            "capital_at_most_25pct_conservative_capacity",
            "portfolio_risk_contribution_at_most_10pct",
            "adv_cap_2pct",
        ]
    },
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


def build_strategy(
    signals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    pretrade = pd.Series(dtype=float)
    monthly_rows: list[dict[str, object]] = []
    holding_rows: list[dict[str, object]] = []
    stock_active_contribution: defaultdict[str, float] = defaultdict(float)
    exchange_active_contribution: defaultdict[str, float] = defaultdict(float)
    target_failures = 0
    target_failure_details: list[dict[str, object]] = []
    excluded_boundary_months: list[dict[str, object]] = []
    for signal_date, month in signals.groupby("signal_date", sort=True):
        indexed = month.drop_duplicates("ts_code").set_index("ts_code")
        benchmark_sample = indexed[
            indexed["eligible_entry"].fillna(False)
            & indexed["mark_return_1m"].notna()
            & indexed["l1_code"].notna()
        ]
        candidates = indexed[indexed["investable_c7"].fillna(False)].reset_index()
        if len(candidates) < 100 or benchmark_sample.empty:
            excluded_boundary_months.append(
                {
                    "signal_date": pd.Timestamp(signal_date).date().isoformat(),
                    "reason": "warmup_or_incomplete_forward_month",
                    "candidates": int(len(candidates)),
                }
            )
            continue
        benchmark_industry = (
            benchmark_sample["l1_code"].astype(str).value_counts(normalize=True)
        )
        try:
            target = constrained_rank_target(
                candidates,
                benchmark_industry,
                count=100,
                stock_cap=STOCK_CAP,
                positive_industry_active_cap=INDUSTRY_ACTIVE_CAP,
            )
        except ValueError as error:
            target_failures += 1
            target_failure_details.append(
                {
                    "signal_date": pd.Timestamp(signal_date).date().isoformat(),
                    "reason": str(error),
                    "candidates": int(len(candidates)),
                }
            )
            continue

        forced_exit = (
            indexed["delist_date"].notna()
            & indexed["entry_date"].notna()
            & indexed["delist_date"].le(indexed["entry_date"])
        )
        can_trade = indexed["entry_tradable"].fillna(False) | forced_exit
        actual, turnover = enforce_execution_and_turnover(
            target, pretrade, can_trade, turnover_cap=1.0
        )
        if actual.empty:
            target_failures += 1
            continue
        names = actual.index.union(pretrade.index)
        trade_weight = actual.reindex(names).fillna(0.0) - pretrade.reindex(names).fillna(0.0)
        impact_cost, participation = square_root_impact_cost(
            trade_weight,
            indexed["adv20_cny"],
            capital_cny=CAPITAL_CNY,
            reference_participation=ADV_CAP,
        )
        base_cost = turnover * 0.0005
        returns = indexed["mark_return_1m"].reindex(actual.index)
        realized = returns.fillna(-1.0)
        gross_return = float((actual * realized).sum())
        net_return = gross_return - base_cost - impact_cost
        benchmark_return = float(benchmark_sample["mark_return_1m"].mean())

        industry_weights = actual.groupby(
            indexed["l1_code"].reindex(actual.index).astype(str)
        ).sum()
        active_industry = industry_weights.subtract(
            benchmark_industry.reindex(industry_weights.index).fillna(0.0)
        )
        monthly_rows.append(
            {
                "index_code": "ALL_A_EQUAL_WEIGHT",
                "signal_date": signal_date,
                "portfolio_gross_return": gross_return,
                "portfolio_net_return": net_return,
                "benchmark_return": benchmark_return,
                "turnover": turnover,
                "base_cost": base_cost,
                "impact_cost": impact_cost,
                "holdings": int(len(actual)),
                "maximum_stock_weight": float(actual.max()),
                "maximum_positive_industry_active_weight": float(active_industry.max()),
                "maximum_trade_participation": float(participation.max()),
                "trades_above_2pct_adv": int(participation.gt(ADV_CAP + 1e-12).sum()),
                "trades_missing_adv20": int(participation.isna().sum()),
                "missing_return_weight": float(actual[returns.isna()].sum()),
            }
        )
        holding_rows.extend(
            {
                "index_code": "ALL_A_EQUAL_WEIGHT",
                "signal_date": signal_date,
                "ts_code": name,
                "l1_code": str(indexed.at[name, "l1_code"]),
                "weight": float(weight),
                "trade_weight": float(trade_weight.get(name, 0.0)),
                "adv20_cny": float(indexed.at[name, "adv20_cny"]),
                "trade_participation": float(participation.get(name, np.nan)),
                "gross_contribution": float(weight * realized.get(name, -1.0)),
            }
            for name, weight in actual.items()
        )

        benchmark_weight = 1.0 / len(benchmark_sample)
        all_names = benchmark_sample.index.union(actual.index)
        all_returns = indexed["mark_return_1m"].reindex(all_names).fillna(-1.0)
        active_weights = actual.reindex(all_names).fillna(0.0)
        active_weights = active_weights - pd.Series(
            benchmark_weight, index=benchmark_sample.index
        ).reindex(all_names).fillna(0.0)
        contributions = active_weights * all_returns
        for name, contribution in contributions.items():
            stock_active_contribution[str(name)] += float(contribution)
            exchange_active_contribution[str(name).split(".")[-1]] += float(contribution)

        growth = 1.0 + gross_return
        pretrade = actual * (1.0 + realized) / growth if growth > 0 else actual
        pretrade = pretrade[pretrade > 1e-14]

    return (
        pd.DataFrame(monthly_rows),
        pd.DataFrame(holding_rows),
        {
            "target_failures": target_failures,
            "target_failure_details": target_failure_details,
            "excluded_boundary_months": excluded_boundary_months,
            "stock_active_contribution": dict(stock_active_contribution),
            "exchange_active_contribution": dict(exchange_active_contribution),
        },
    )


def stage_s_gates(summary: dict[str, object]) -> dict[str, bool]:
    return {
        "partial_rank_ic_gt_003": float(summary["partial_rank_ic_6m"]) > 0.03,
        "positive_ic_month_share_gt_055": float(summary["positive_ic_month_share"]) > 0.55,
        "middle_liquidity_ic_positive": float(summary["middle_liquidity_rank_ic_6m"]) > 0,
        "highest_liquidity_ic_positive": float(summary["highest_liquidity_rank_ic_6m"]) > 0,
    }


def stage_p_evaluation(
    monthly: pd.DataFrame,
    holdings: pd.DataFrame,
    construction: dict[str, object],
) -> dict[str, object]:
    metrics = performance_metrics(monthly)
    annual = monthly.assign(
        active=monthly["portfolio_net_return"] - monthly["benchmark_return"]
    ).groupby(monthly["signal_date"].dt.year).agg(
        active=("active", "sum"), months=("signal_date", "size")
    )
    complete_years = annual[annual["months"].eq(12)]["active"].sort_index()
    latest_two = complete_years.tail(2)
    stock_contribution = pd.Series(
        construction["stock_active_contribution"], dtype=float
    )
    total_gross_active = float(
        (monthly["portfolio_gross_return"] - monthly["benchmark_return"]).sum()
    )
    maximum_stock_share = (
        float(stock_contribution.max() / total_gross_active)
        if total_gross_active > 0 and not stock_contribution.empty
        else None
    )
    trade = holdings[holdings["trade_weight"].abs().gt(1e-14)].copy()
    capacity = ADV_CAP * trade["adv20_cny"] / trade["trade_weight"].abs()
    minimum_capacity = float(capacity.min()) if len(capacity) else 0.0
    constraints = {
        "months_not_100_holdings": int(monthly["holdings"].ne(100).sum()),
        "stock_weight_violations": int(
            monthly["maximum_stock_weight"].gt(STOCK_CAP + 1e-8).sum()
        ),
        "industry_active_violations": int(
            monthly["maximum_positive_industry_active_weight"].gt(
                INDUSTRY_ACTIVE_CAP + 1e-8
            ).sum()
        ),
        "trade_participation_violations": int(monthly["trades_above_2pct_adv"].sum()),
        "trades_missing_adv20": int(monthly["trades_missing_adv20"].sum()),
        "missing_return_months": int(monthly["missing_return_weight"].gt(0).sum()),
        "target_failures": int(construction["target_failures"]),
    }
    gates = {
        "annual_net_excess_gt_004": metrics["annual_excess_return_difference"] > 0.04,
        "information_ratio_gt_060": metrics["information_ratio"] > 0.60,
        "maximum_stock_contribution_lt_015": (
            maximum_stock_share is not None and maximum_stock_share < 0.15
        ),
        "capacity_10m_pass": (
            minimum_capacity >= CAPITAL_CNY - 1e-6
            and constraints["trade_participation_violations"] == 0
            and constraints["trades_missing_adv20"] == 0
        ),
        "latest_two_complete_years_not_both_negative": (
            len(latest_two) == 2 and not bool(latest_two.lt(0).all())
        ),
        "constraints_pass": not any(constraints.values()),
    }
    gates["passes_all"] = all(gates.values())
    exchange_contribution = pd.Series(
        construction["exchange_active_contribution"], dtype=float
    )
    return {
        "metrics": metrics,
        "annual_additive_active": {
            str(index): float(value)
            for index, value in annual["active"].items()
        },
        "latest_two_complete_years": {
            str(index): float(value) for index, value in latest_two.items()
        },
        "maximum_stock_contribution_share": maximum_stock_share,
        "exchange_active_contribution": exchange_contribution.to_dict(),
        "minimum_capacity_at_2pct_cny": minimum_capacity,
        "constraints": constraints,
        "target_failure_details": construction["target_failure_details"],
        "excluded_boundary_months": construction["excluded_boundary_months"],
        "gates": gates,
    }


def lane_a_marginal_diagnostic(
    c7_monthly: pd.DataFrame,
    lane_a_monthly: pd.DataFrame,
    sleeve_weight: float = 0.20,
) -> dict[str, object]:
    """Post-decision diagnostic only; it cannot change the C7 decision."""
    rows: dict[str, object] = {}
    c7 = c7_monthly[
        ["signal_date", "portfolio_net_return", "benchmark_return"]
    ].rename(
        columns={
            "portfolio_net_return": "c7_return",
            "benchmark_return": "c7_benchmark",
        }
    )
    for benchmark, baseline in lane_a_monthly.groupby("index_code", sort=True):
        merged = baseline.merge(c7, on="signal_date", how="inner", validate="one_to_one")
        baseline_active = merged["portfolio_net_return"] - merged["benchmark_return"]
        combined_return = (
            (1.0 - sleeve_weight) * merged["portfolio_net_return"]
            + sleeve_weight * merged["c7_return"]
        )
        combined_active = combined_return - merged["benchmark_return"]
        baseline_ir = float(
            baseline_active.mean() / baseline_active.std(ddof=1) * np.sqrt(12)
        )
        combined_ir = float(
            combined_active.mean() / combined_active.std(ddof=1) * np.sqrt(12)
        )
        c7_active = merged["c7_return"] - merged["c7_benchmark"]
        rows[str(benchmark)] = {
            "months": int(len(merged)),
            "sleeve_weight": sleeve_weight,
            "baseline_ir": baseline_ir,
            "combined_ir": combined_ir,
            "delta_ir": combined_ir - baseline_ir,
            "baseline_max_drawdown": maximum_drawdown(
                merged["portfolio_net_return"]
            ),
            "combined_max_drawdown": maximum_drawdown(combined_return),
            "active_return_correlation": float(baseline_active.corr(c7_active)),
        }
    return {
        "status": "POST_DECISION_DIAGNOSTIC_NOT_A_PROMOTION_GATE",
        "reason": "GOAL_V7 requires Lane A marginal evidence; C7 registration omitted it, so this diagnostic cannot rescue or change REJECTED",
        "benchmarks": rows,
    }


def update_ledger(
    hac: dict[str, object],
    decision: str,
    output_dir: Path,
) -> dict[str, object]:
    v6_path = output_dir / "multiple_testing_ledger_v6.csv"
    v7_path = output_dir / "multiple_testing_ledger_v7.csv"
    ledger = pd.read_csv(v7_path if v7_path.exists() else v6_path)
    ledger = ledger[ledger["factor"].ne(RESEARCH_ID)].copy()
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": RESEARCH_ID,
        "family": "capacity_aware_quality_adjusted_value",
        "research_version": "V7_post_v6_preregistered",
        "primary_statistic": "historical_development_6m_partial_rank_ic_hac_t",
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
    ledger.to_csv(v7_path, index=False, encoding="utf-8-sig")
    row = ledger[ledger["factor"].eq(RESEARCH_ID)].iloc[-1]
    return {
        "trial_id": int(row["trial_id"]),
        "q_value": float(row["bh_q_value_global"]),
        "bh_fdr_5pct": bool(row["bh_fdr_5pct"]),
        "ledger_path": str(v7_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/evaluations")
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    validate_registration(REGISTRATION)

    panel = prepare_panel(args.artifact_dir)
    panel["listed_days"] = (panel["signal_date"] - panel["list_date"]).dt.days
    entries = panel[["ts_code", "signal_date", "entry_date"]].copy()
    daily_path = args.artifact_dir / "tushare" / "daily_basic_full.parquet"
    daily = pd.read_parquet(daily_path, columns=["ts_code", "trade_date"])
    effective = effective_days_last_60(daily, entries)
    panel = panel.merge(
        effective[["ts_code", "signal_date", "effective_days_60"]],
        on=["ts_code", "signal_date"],
        validate="one_to_one",
    )
    del daily, effective
    signals = add_capacity_aware_signals(panel)
    signals["investable_c7"] = (
        signals["eligible_entry"].fillna(False)
        & signals["listed_days"].ge(250)
        & signals["effective_days_60"].ge(EFFECTIVE_DAYS_MINIMUM)
        & signals["adv20_cny"].ge(CAPITAL_CNY)
        & signals["raw_signal"].notna()
    )

    signal_columns = [
        "ts_code",
        "signal_date",
        "entry_date",
        "entry_tradable",
        "eligible_entry",
        "investable_c7",
        "l1_code",
        "listed_days",
        "effective_days_60",
        "adv20_cny",
        "baseline_value_z",
        "baseline_quality_z",
        "raw_signal",
        "liquidity_neutral_signal",
        "industry_within_signal",
        "partial_signal",
    ]
    signal_path = args.output_dir / "c7_capacity_aware_qav_signals.parquet"
    signals[signal_columns].to_parquet(signal_path, index=False)

    source_hashes = {
        "style_panel": sha256_file(
            args.artifact_dir / "factor_panel_style_baseline_v5.parquet"
        ),
        "execution_labels": sha256_file(
            args.artifact_dir / "portfolio_execution_labels_v5.parquet"
        ),
        "adv20": sha256_file(args.artifact_dir / "adv20_capacity_v5.parquet"),
        "daily_basic": sha256_file(daily_path),
        "slow_labels": sha256_file(
            args.artifact_dir / "slow_horizon_labels_v4_t1_open.parquet"
        ),
        "registration": sha256_file(REGISTRATION_PATH),
    }
    monthly_coverage = (
        signals.loc[signals["investable_c7"]]
        .groupby("signal_date")
        .size()
    )
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
        "investable_rows": int(signals["investable_c7"].sum()),
        "investable_symbols": int(
            signals.loc[signals["investable_c7"], "ts_code"].nunique()
        ),
        "investable_months": int(len(monthly_coverage)),
        "minimum_monthly_investable_symbols": int(monthly_coverage.min()),
        "missing_effective_days_for_eligible": int(
            signals.loc[
                signals["eligible_entry"].fillna(False), "effective_days_60"
            ].isna().sum()
        ),
        "pit_protocol": (
            "QAV inherits announcement-date/version-controlled V5 panel; "
            "60-day liquidity, ADV20 and investability use data available by T+1 entry"
        ),
        "sources": source_hashes,
        "config_sha256": config_sha256(),
    }
    if (
        audit["duplicate_keys"]
        or audit["future_information_violations"]
        or audit["minimum_monthly_investable_symbols"] < 100
    ):
        audit["status"] = "DATA_BLOCKED"
    audit_path = Path("artifacts/data_audits/c7_capacity_aware_qav.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"event": "data_audit", **audit}, ensure_ascii=False), flush=True)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: C7 data audit failed")

    labels = pd.read_parquet(
        args.artifact_dir / "slow_horizon_labels_v4_t1_open.parquet"
    )
    labels["signal_date"] = pd.to_datetime(labels["signal_date"])
    signal_monthly, signal_summary = monthly_signal_diagnostics(signals, labels)
    signal_monthly_path = (
        args.output_dir / "c7_capacity_aware_qav_signal_monthly.parquet"
    )
    signal_monthly.to_parquet(signal_monthly_path, index=False)
    hac = hac_mean_test(signal_monthly["partial_rank_ic_6m"].dropna())
    signal_summary["hac"] = hac
    signal_gates = stage_s_gates(signal_summary)
    signal_gates["passes_all"] = all(signal_gates.values())
    signal_status = "SIGNAL_VALID" if signal_gates["passes_all"] else "REJECTED"

    result: dict[str, object] = {
        "research_id": RESEARCH_ID,
        "registration_sha256": source_hashes["registration"],
        "config_sha256": config_sha256(),
        "evidence_scope": "historical_development",
        "data_audit": audit,
        "stage_s": {
            "summary": signal_summary,
            "gates": signal_gates,
            "status": signal_status,
        },
        "stage_p": {"ran": False, "reason": "Stage S did not pass"},
    }
    decision = "REJECTED"
    if can_run_stage_p(signal_status):
        monthly, holdings, construction = build_strategy(signals)
        monthly_path = args.output_dir / "c7_capacity_aware_qav_monthly.parquet"
        holdings_path = args.output_dir / "c7_capacity_aware_qav_holdings.parquet"
        monthly.to_parquet(monthly_path, index=False)
        holdings.to_parquet(holdings_path, index=False)
        portfolio = stage_p_evaluation(monthly, holdings, construction)
        lane_a = pd.read_parquet(
            args.artifact_dir
            / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"
        )
        portfolio["lane_a_marginal_diagnostic"] = lane_a_marginal_diagnostic(
            monthly, lane_a
        )
        decision = (
            "RESEARCH_SHADOW" if portfolio["gates"]["passes_all"] else "REJECTED"
        )
        result["stage_p"] = {
            "ran": True,
            **portfolio,
        }

    validate_research_decision(
        decision,
        evidence_scope="historical_development",
        live_observations=0,
        required_live_observations=12,
    )
    result["decision"] = decision
    result["multiple_testing"] = update_ledger(hac, decision, args.output_dir)

    if decision == "RESEARCH_SHADOW":
        shadow_dir = Path("artifacts/live_shadow_v7/c7_capacity_aware_qav")
        shadow_dir.mkdir(parents=True, exist_ok=True)
        shadow_manifest = {
            "research_id": RESEARCH_ID,
            "status": "WAITING_FOR_APPEND_ONLY_LIVE_DATA",
            "first_eligible_signal_date": "2026-07-01 or later",
            "observations": 0,
            "required_months": 12,
            "registration_sha256": source_hashes["registration"],
            "config_sha256": config_sha256(),
            "historical_results_are_not_live": True,
        }
        (shadow_dir / "manifest.json").write_text(
            json.dumps(shadow_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    result_path = args.output_dir / "c7_capacity_aware_qav_evaluation.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "decision",
                "research_id": RESEARCH_ID,
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
