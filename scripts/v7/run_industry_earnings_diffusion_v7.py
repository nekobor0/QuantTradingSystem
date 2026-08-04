"""Run preregistered F7 CSI1000 industry earnings diffusion research."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_trading_system.research.alpha_phase1.portfolio_v5 import (
    enforce_execution_and_turnover,
    performance_metrics,
)
from quant_trading_system.research.v6.industry_rotation import build_industry_momentum_scores
from quant_trading_system.research.v7.industry_earnings_diffusion import (
    aggregate_industry_diffusion,
    analyst_revision_pit,
    build_csi1000_member_panel,
    financial_acceleration_pit,
    forward_industry_returns,
    industry_tilts,
    monthly_partial_rank_ic,
    monthly_rank_ic,
)
from quant_trading_system.research.v7.governance import (
    can_run_stage_p,
    validate_registration,
    validate_research_decision,
)
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.evaluate_capacity_v5 import summarize as summarize_capacity
from scripts.v6.update_multiple_testing_v6 import hac_mean_test
from scripts.v7.backfill_f7_financials import _load_verified_report_marker


RESEARCH_ID = "F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION"
REGISTRATION = Path("artifacts/registrations/f7_industry_earnings_diffusion.md")
REGISTRATION_CONFIG = {
    "research_id": RESEARCH_ID,
    "post_v6_hypothesis": True,
    "core_horizon": "3m",
    "primary_benchmark": "000852.SH",
    "role": "BENCHMARK_SPECIFIC",
    "variant_count": 1,
    "historical_evidence_use": "development_only",
    "live_confirmation": {"unit": "months", "minimum": 12},
    "relaxations": {
        "cross_benchmark_consistency": [
            "single preregistered benchmark 000852.SH",
            "fixed 10 percent zero-net industry overlay",
            "2 percent industry active cap and tracking-error gate",
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
    payload = json.dumps(REGISTRATION_CONFIG, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_data_manifest(
    financial_paths: list[Path],
    report_paths: list[Path],
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    def summarize(paths: list[Path]) -> dict[str, Any]:
        entries = []
        root_digest = hashlib.sha256()
        total_rows = 0
        for path in sorted(Path(value) for value in paths):
            resolved = path.resolve()
            try:
                display_path = resolved.relative_to(project_root.resolve()).as_posix()
            except ValueError:
                display_path = resolved.as_posix()
            digest = sha256_file(resolved)
            sidecar = resolved.with_suffix(".json")
            if sidecar.exists():
                rows = int(json.loads(sidecar.read_text(encoding="utf-8"))["rows"])
            else:
                rows = int(len(pd.read_parquet(resolved)))
            entries.append({"path": display_path, "rows": rows, "sha256": digest})
            total_rows += rows
            root_digest.update(f"{display_path}\0{rows}\0{digest}\n".encode())
        return {
            "files": len(entries),
            "rows": total_rows,
            "root_sha256": root_digest.hexdigest(),
            "entries": entries,
        }

    return {
        "version": 1,
        "research_id": RESEARCH_ID,
        "datasets": {
            "fina_indicator": summarize(financial_paths),
            "report_rc": summarize(report_paths),
        },
    }


def raw_data_quality(financial: pd.DataFrame, reports: pd.DataFrame) -> dict[str, Any]:
    financial_fields = [
        "ts_code",
        "ann_date",
        "end_date",
        "update_flag",
        "q_sales_yoy",
        "dt_netprofit_yoy",
        "q_roe",
    ]
    report_fields = ["ts_code", "report_date", "org_name", "quarter", "np", "create_time"]
    financial_dates = pd.to_datetime(financial["ann_date"].astype("string"), format="mixed", errors="coerce")
    report_dates = pd.to_datetime(reports["report_date"].astype("string"), format="mixed", errors="coerce")
    report_np = pd.to_numeric(reports["np"], errors="coerce")
    report_month = report_dates.dt.to_period("M")
    monthly = reports.assign(_month=report_month).dropna(subset=["_month"]).groupby("_month")
    organizations = monthly["org_name"].nunique() if len(reports) else pd.Series(dtype=float)
    stocks = monthly["ts_code"].nunique() if len(reports) else pd.Series(dtype=float)
    return {
        "financial_exact_duplicate_rows": int(financial.duplicated(financial_fields).sum()),
        "report_exact_duplicate_rows": int(reports.duplicated(report_fields).sum()),
        "financial_unparseable_ann_date_rows": int(financial_dates.isna().sum()),
        "report_unparseable_report_date_rows": int(report_dates.isna().sum()),
        "financial_unparseable_ann_date_sample": financial.loc[
            financial_dates.isna(), ["ts_code", "end_date"]
        ].astype("string").head(10).to_dict("records"),
        "report_unparseable_report_date_sample": reports.loc[
            report_dates.isna(), ["ts_code", "quarter"]
        ].astype("string").head(10).to_dict("records"),
        "financial_field_nonmissing_ratio": {
            field: float(financial[field].notna().mean()) for field in financial_fields
        },
        "report_field_nonmissing_ratio": {
            field: float(reports[field].notna().mean()) for field in report_fields
        },
        "report_organizations": int(reports["org_name"].nunique(dropna=True)),
        "report_stocks": int(reports["ts_code"].nunique(dropna=True)),
        "report_target_quarters": int(reports["quarter"].nunique(dropna=True)),
        "report_nonpositive_np_rows": int(report_np.le(0).sum()),
        "report_month_min_organizations": int(organizations.min()) if len(organizations) else 0,
        "report_month_min_stocks": int(stocks.min()) if len(stocks) else 0,
    }


def prepare_execution_labels(
    labels: pd.DataFrame,
    stock_basic: pd.DataFrame,
    stock_st: pd.DataFrame,
    adv20: pd.DataFrame,
) -> pd.DataFrame:
    output = labels.copy()
    for column in ("signal_date", "entry_date", "exit_date"):
        output[column] = pd.to_datetime(output[column])
    lifecycle = stock_basic[["ts_code", "delist_date"]].copy()
    lifecycle["delist_date"] = pd.to_datetime(lifecycle["delist_date"], errors="coerce")
    output = output.merge(lifecycle, on="ts_code", how="left", validate="many_to_one")
    st = stock_st[["ts_code", "trade_date"]].drop_duplicates().copy()
    st["signal_date"] = pd.to_datetime(st.pop("trade_date").astype("string"), format="%Y%m%d")
    st["is_st"] = True
    output = output.merge(st, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    output["is_st"] = output["is_st"].eq(True)
    adv = adv20[["ts_code", "signal_date", "entry_date", "adv20_cny"]].copy()
    adv["signal_date"] = pd.to_datetime(adv["signal_date"])
    adv["entry_date"] = pd.to_datetime(adv["entry_date"])
    output = output.merge(adv, on=["ts_code", "signal_date", "entry_date"], how="left", validate="one_to_one")
    output["forced_exit"] = output["delist_date"].notna() & output["delist_date"].le(output["entry_date"])
    not_delisted = output["delist_date"].isna() | output["delist_date"].gt(output["entry_date"])
    output["eligible_entry"] = (
        output["entry_tradable"].fillna(False)
        & ~output["is_st"]
        & not_delisted
        & output["mark_return_1m"].notna()
        & output["adv20_cny"].gt(0)
    )
    return output


def load_verified_shards(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        sidecar = path.with_suffix(".json")
        if not sidecar.exists():
            raise ValueError(f"missing shard sidecar: {path}")
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        if metadata.get("sha256") != sha256_file(path):
            raise ValueError(f"shard hash drift: {path}")
        frame = pd.read_parquet(path)
        if len(frame) != metadata.get("rows"):
            raise ValueError(f"shard row drift: {path}")
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def require_complete_backfill(backfill_dir: Path, expected_symbols: int, expected_months: set[str]) -> dict[str, Any]:
    financial_paths = sorted((backfill_dir / "shards" / "fina_indicator").glob("*.parquet"))
    markers = sorted(
        path
        for path in (backfill_dir / "shards" / "report_rc").glob("*.complete.json")
        if path.name[:6] in expected_months
    )
    if len(financial_paths) != expected_symbols or len(markers) != len(expected_months):
        raise SystemExit(
            f"F7 backfill incomplete: financial {len(financial_paths)}/{expected_symbols}, "
            f"report months {len(markers)}/{len(expected_months)}"
        )
    report_paths = []
    for marker in markers:
        period = pd.Period(marker.name[:6], freq="M")
        payload = _load_verified_report_marker(
            marker,
            period.start_time.strftime("%Y%m%d"),
            period.end_time.strftime("%Y%m%d"),
        )
        for page in payload["pages"]:
            path = Path(page["path"])
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.exists() or sha256_file(path) != page["sha256"]:
                raise ValueError(f"report page drift: {path}")
            report_paths.append(path)
    return {
        "financial_paths": financial_paths,
        "report_paths": sorted(set(report_paths)),
        "financial_shards": len(financial_paths),
        "report_months": len(markers),
    }


def one_month_industry_returns(members: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    source = labels[["signal_date", "ts_code", "exit_date", "mark_return_1m"]].copy()
    source["signal_date"] = pd.to_datetime(source["signal_date"])
    source["exit_date"] = pd.to_datetime(source["exit_date"])
    panel = members.merge(source, on=["signal_date", "ts_code"], how="left", validate="one_to_one")
    rows = []
    for (signal_date, industry), group in panel.groupby(["signal_date", "l1_code"], sort=True):
        total = group["benchmark_weight"].sum()
        valid = group["mark_return_1m"].notna() & group["benchmark_weight"].gt(0)
        covered = group.loc[valid, "benchmark_weight"].sum()
        coverage = float(covered / total) if total > 0 else np.nan
        value = float(np.average(group.loc[valid, "mark_return_1m"], weights=group.loc[valid, "benchmark_weight"])) if valid.any() and coverage >= 0.95 else np.nan
        rows.append({"signal_date": signal_date, "exit_date": group["exit_date"].max(), "l1_code": industry, "industry_return": value, "return_weight_coverage": coverage})
    return pd.DataFrame(rows)


def coverage_audit(scores: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    components = [
        "positive_revenue_acceleration_share",
        "positive_deducted_profit_acceleration_share",
        "positive_roe_improvement_share",
        "earnings_revision_weighted_median",
    ]
    rows = []
    for signal_date, month in scores.groupby("signal_date", sort=True):
        industries = month["l1_code"].nunique()
        item: dict[str, Any] = {"signal_date": signal_date, "industries": industries}
        for component in components:
            item[f"{component}_coverage"] = float(month[component].notna().sum() / industries) if industries else 0.0
        item["valid_industries"] = int(month["industry_earnings_diffusion"].notna().sum())
        item["month_pass"] = bool(
            item["valid_industries"] >= 15
            and all(item[f"{component}_coverage"] >= 0.80 for component in components)
        )
        rows.append(item)
    monthly = pd.DataFrame(rows)
    passing = monthly.loc[monthly["month_pass"], "signal_date"]
    audit = {
        "months": int(len(monthly)),
        "passing_months": int(monthly["month_pass"].sum()),
        "minimum_required_passing_months": 60,
        "passes": bool(monthly["month_pass"].sum() >= 60),
        "first_passing_month": str(passing.min().date()) if len(passing) else None,
        "last_passing_month": str(passing.max().date()) if len(passing) else None,
    }
    return monthly, audit


def stage_s(scores: pd.DataFrame, future: pd.DataFrame, momentum: pd.DataFrame, valid_dates: set[pd.Timestamp]) -> dict[str, Any]:
    merged = scores.merge(future, on=["signal_date", "l1_code"], how="inner", validate="one_to_one").merge(
        momentum[["signal_date", "l1_code", "relative_momentum"]],
        on=["signal_date", "l1_code"],
        how="left",
        validate="one_to_one",
    )
    merged = merged[merged["signal_date"].isin(valid_dates)].dropna(
        subset=["industry_earnings_diffusion", "industry_return_3m"]
    )
    rank_ic = monthly_rank_ic(merged, "industry_earnings_diffusion", "industry_return_3m")
    partial_ic = monthly_partial_rank_ic(
        merged,
        "industry_earnings_diffusion",
        "industry_return_3m",
        "relative_momentum",
    )
    hac = hac_mean_test(rank_ic)
    component_columns = [
        "positive_revenue_acceleration_share",
        "positive_deducted_profit_acceleration_share",
        "positive_roe_improvement_share",
        "earnings_revision_weighted_median",
    ]
    component_rank_ic = {}
    for component in component_columns:
        values = monthly_rank_ic(merged, component, "industry_return_3m")
        component_rank_ic[component] = {
            "months": int(len(values)),
            "mean_rank_ic_3m": float(values.mean()),
            "positive_ic_month_share": float(values.gt(0).mean()),
        }
    annual_rank_ic = (
        rank_ic.rename("mean_rank_ic_3m")
        .reset_index()
        .assign(year=lambda frame: frame["signal_date"].dt.year)
        .groupby("year", as_index=False)["mean_rank_ic_3m"]
        .agg(["count", "mean"])
        .reset_index()
        .rename(columns={"count": "months", "mean": "mean_rank_ic_3m"})
        .to_dict("records")
    )
    industry_diagnostics = []
    for industry, group in merged.groupby("l1_code", sort=True):
        valid = group[["industry_earnings_diffusion", "industry_return_3m"]].dropna()
        correlation = np.nan
        if (
            len(valid) >= 3
            and valid["industry_earnings_diffusion"].nunique() > 1
            and valid["industry_return_3m"].nunique() > 1
        ):
            correlation = valid["industry_earnings_diffusion"].corr(
                valid["industry_return_3m"], method="spearman"
            )
        industry_diagnostics.append(
            {
                "l1_code": industry,
                "observations": int(len(valid)),
                "spearman_signal_return": float(correlation),
                "mean_future_return_3m": float(valid["industry_return_3m"].mean()),
            }
        )
    gates = {
        "mean_rank_ic_3m_gt_005": bool(rank_ic.mean() > 0.05),
        "positive_ic_month_share_gt_055": bool(rank_ic.gt(0).mean() > 0.55),
        "price_momentum_partial_ic_gt_0": bool(partial_ic.mean() > 0),
        "minimum_60_months": bool(len(rank_ic) >= 60),
    }
    return {
        "rows": int(len(merged)),
        "months": int(len(rank_ic)),
        "mean_rank_ic_3m": float(rank_ic.mean()),
        "positive_ic_month_share": float(rank_ic.gt(0).mean()),
        "price_momentum_partial_rank_ic": float(partial_ic.mean()),
        "partial_ic_months": int(len(partial_ic)),
        "hac": hac,
        "component_rank_ic": component_rank_ic,
        "annual_rank_ic": annual_rank_ic,
        "industry_diagnostics": industry_diagnostics,
        "gates": {**gates, "passes_all": all(gates.values())},
        "monthly_rank_ic": rank_ic.rename("rank_ic").reset_index().to_dict("records"),
    }


def build_overlay_portfolio(
    scores: pd.DataFrame,
    members: pd.DataFrame,
    labels: pd.DataFrame,
    baseline_monthly: pd.DataFrame,
    baseline_holdings: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tilts = industry_tilts(scores)
    label_columns = ["signal_date", "ts_code", "mark_return_1m"]
    for column in ("entry_tradable", "eligible_entry", "forced_exit"):
        if column in labels:
            label_columns.append(column)
    label_frame = labels[label_columns].copy()
    if "entry_tradable" not in label_frame:
        label_frame["entry_tradable"] = True
    if "eligible_entry" not in label_frame:
        label_frame["eligible_entry"] = label_frame["entry_tradable"]
    if "forced_exit" not in label_frame:
        label_frame["forced_exit"] = False
    label_map = label_frame.set_index(["signal_date", "ts_code"])
    member_map = {date: frame.set_index("ts_code") for date, frame in members.groupby("signal_date")}
    tilt_map = {date: frame.set_index("l1_code")["industry_tilt"] for date, frame in tilts.groupby("signal_date")}
    previous_overlay = pd.Series(dtype=float)
    pretrade_target = pd.Series(dtype=float)
    monthly_rows = []
    holding_rows = []
    contribution_rows = []
    base_monthly = baseline_monthly.set_index("signal_date")
    for signal_date, base in baseline_holdings.groupby("signal_date", sort=True):
        signal_date = pd.Timestamp(signal_date)
        if signal_date not in tilt_map or signal_date not in member_map or signal_date not in base_monthly.index:
            continue
        member = member_map[signal_date]
        base_weights = base.set_index("ts_code")["weight"].astype(float)
        month_labels = label_map.loc[signal_date]
        tradable = month_labels["entry_tradable"].fillna(False)
        eligible_entry = month_labels["eligible_entry"].fillna(False)
        can_rebalance = tradable | month_labels["forced_exit"].fillna(False)
        overlay_parts = []
        for industry, tilt in tilt_map[signal_date].items():
            industry_names = member.index[member["l1_code"].eq(industry)]
            if tilt > 0:
                allocation = member.loc[industry_names, "benchmark_weight"].where(
                    eligible_entry.reindex(industry_names).fillna(False), 0.0
                )
            else:
                allocation = base_weights.reindex(industry_names).fillna(0.0).where(
                    can_rebalance.reindex(industry_names).fillna(False), 0.0
                )
            if allocation.sum() <= 0:
                raise ValueError(f"cannot allocate industry tilt {industry} at {signal_date.date()}")
            overlay_parts.append(allocation / allocation.sum() * tilt)
        overlay = pd.concat(overlay_parts).groupby(level=0).sum()
        target = base_weights.add(overlay, fill_value=0.0)
        if target.min() < -1e-10 or abs(target.sum() - 1.0) > 1e-8:
            raise ValueError(f"overlay violates long-only/full-investment at {signal_date.date()}")
        can_trade = can_rebalance.reindex(target.index.union(pretrade_target.index)).fillna(False)
        actual, turnover = enforce_execution_and_turnover(target, pretrade_target, can_trade, turnover_cap=1.0)
        returns = month_labels["mark_return_1m"].reindex(actual.index)
        missing_return_weight = float(actual[returns.isna()].sum())
        realized_returns = returns.fillna(-1.0)
        actual_overlay = actual.subtract(base_weights, fill_value=0.0)
        overlay_return = float((actual_overlay * realized_returns.reindex(actual_overlay.index)).sum())
        overlay_trade = actual_overlay.subtract(previous_overlay, fill_value=0.0)
        overlay_turnover = float(0.5 * overlay_trade.abs().sum())
        total_trade = actual.subtract(pretrade_target, fill_value=0.0)
        gross_return = float((actual * realized_returns).sum())
        stock_industry = member["l1_code"].reindex(actual.index.union(base_weights.index))
        if stock_industry.isna().any():
            raise ValueError(f"candidate holding lacks PIT industry at {signal_date.date()}")
        actual_industry = actual.groupby(stock_industry.reindex(actual.index)).sum()
        base_industry = base_weights.groupby(stock_industry.reindex(base_weights.index)).sum()
        realized_tilt = actual_industry.subtract(base_industry, fill_value=0.0)
        base_row = base_monthly.loc[signal_date]
        monthly_rows.append(
            {
                "index_code": "000852.SH",
                "signal_date": signal_date,
                "portfolio_gross_return": gross_return,
                "portfolio_net_return": gross_return - turnover * 0.0005,
                "benchmark_return": float(base_row["benchmark_return"]),
                "turnover": turnover,
                "cost": turnover * 0.0005,
                "overlay_return": overlay_return,
                "overlay_turnover": overlay_turnover,
                "maximum_industry_tilt": float(tilt_map[signal_date].abs().max()),
                "industry_tilt_l1": float(tilt_map[signal_date].abs().sum()),
                "realized_maximum_industry_tilt": float(realized_tilt.abs().max()),
                "realized_industry_tilt_l1": float(realized_tilt.abs().sum()),
                "minimum_stock_weight": float(actual.min()),
                "missing_return_weight": missing_return_weight,
            }
        )
        holding_rows.extend(
            {"index_code": "000852.SH", "signal_date": signal_date, "ts_code": stock, "weight": float(weight), "trade_weight": float(total_trade.get(stock, 0.0))}
            for stock, weight in actual[actual.abs().gt(1e-14)].items()
        )
        stock_active_contribution = actual_overlay * realized_returns.reindex(actual_overlay.index)
        industry_active_contribution = stock_active_contribution.groupby(
            stock_industry.reindex(stock_active_contribution.index)
        ).sum()
        for industry, contribution in industry_active_contribution.items():
            contribution_rows.append(
                {
                    "signal_date": signal_date,
                    "l1_code": industry,
                    "active_return_contribution": float(contribution),
                }
            )
        previous_overlay = actual_overlay
        growth = 1.0 + gross_return
        pretrade_target = actual * (1.0 + realized_returns) / growth if growth > 0 else actual
        pretrade_target = pretrade_target[pretrade_target.abs().gt(1e-14)]
    return pd.DataFrame(monthly_rows), pd.DataFrame(holding_rows), pd.DataFrame(contribution_rows)


def stage_p(
    candidate: pd.DataFrame,
    holdings: pd.DataFrame,
    contributions: pd.DataFrame,
    baseline: pd.DataFrame,
    adv_path: Path,
) -> dict[str, Any]:
    common = sorted(set(candidate["signal_date"]).intersection(baseline["signal_date"]))
    candidate = candidate[candidate["signal_date"].isin(common)].sort_values("signal_date")
    baseline = baseline[baseline["signal_date"].isin(common)].sort_values("signal_date")
    base_metrics = performance_metrics(baseline)
    candidate_metrics = performance_metrics(candidate)
    cost_stress = {}
    for rate in (0.0005, 0.001, 0.002):
        stressed_candidate = candidate.assign(
            portfolio_net_return=candidate["portfolio_gross_return"] - candidate["turnover"] * rate
        )
        stressed_baseline = baseline.assign(
            portfolio_net_return=baseline["portfolio_gross_return"] - baseline["turnover"] * rate
        )
        candidate_stress_metrics = performance_metrics(stressed_candidate)
        baseline_stress_metrics = performance_metrics(stressed_baseline)
        cost_stress[str(rate)] = {
            "baseline": baseline_stress_metrics,
            "candidate": candidate_stress_metrics,
            "delta_ir": float(candidate_stress_metrics["information_ratio"] - baseline_stress_metrics["information_ratio"]),
            "annual_net_excess_increment": float(candidate_stress_metrics["annual_excess_return_difference"] - baseline_stress_metrics["annual_excess_return_difference"]),
        }
    concentration = contributions.groupby("l1_code")["active_return_contribution"].sum().abs()
    maximum_contribution = float(concentration.max() / concentration.sum()) if concentration.sum() > 0 else np.inf
    adv = pd.read_parquet(adv_path)
    capacity_frame = holdings.merge(adv, on=["ts_code", "signal_date"], how="left", validate="many_to_one")
    capacity = summarize_capacity(capacity_frame, 10_000_000, 0.05)
    maximum_missing_return_weight = float(
        candidate.get("missing_return_weight", pd.Series(0.0, index=candidate.index)).max()
    )
    gates = {
        "delta_ir_gt_015": candidate_metrics["information_ratio"] - base_metrics["information_ratio"] > 0.15,
        "annual_net_excess_increment_gt_001": candidate_metrics["annual_excess_return_difference"] - base_metrics["annual_excess_return_difference"] > 0.01,
        "tracking_error_increment_lt_0015": candidate_metrics["tracking_error"] - base_metrics["tracking_error"] < 0.015,
        "active_max_drawdown_not_worse_002": candidate_metrics["excess_max_drawdown"] >= base_metrics["excess_max_drawdown"] - 0.02,
        "maximum_industry_contribution_lt_030": maximum_contribution < 0.30,
        "capacity_10m_pass": capacity["trades_missing_adv20"] == 0 and capacity["trades_above_participation_cap"] == 0 and capacity["minimum_capacity_at_cap_cny"] >= 10_000_000 - 1e-6,
        "portfolio_constraints_pass": candidate["maximum_industry_tilt"].le(0.02 + 1e-12).all() and candidate["industry_tilt_l1"].sub(0.10).abs().le(1e-10).all() and candidate["realized_maximum_industry_tilt"].le(0.02 + 1e-10).all() and candidate["realized_industry_tilt_l1"].le(0.10 + 1e-10).all() and candidate["minimum_stock_weight"].ge(-1e-10).all(),
    }
    return {
        "months": len(common),
        "baseline": base_metrics,
        "candidate": candidate_metrics,
        "delta_ir": float(candidate_metrics["information_ratio"] - base_metrics["information_ratio"]),
        "annual_net_excess_increment": float(candidate_metrics["annual_excess_return_difference"] - base_metrics["annual_excess_return_difference"]),
        "tracking_error_increment": float(candidate_metrics["tracking_error"] - base_metrics["tracking_error"]),
        "active_max_drawdown_delta": float(candidate_metrics["excess_max_drawdown"] - base_metrics["excess_max_drawdown"]),
        "maximum_industry_contribution": maximum_contribution,
        "maximum_missing_return_weight": maximum_missing_return_weight,
        "capacity": capacity,
        "cost_stress": cost_stress,
        "gates": {**gates, "passes_all": all(gates.values())},
    }


def update_ledger(result: dict[str, Any], decision: str, ledger_path: Path) -> dict[str, Any]:
    ledger = pd.read_csv(ledger_path)
    existing = ledger[ledger["factor"].eq(RESEARCH_ID)]
    if not existing.empty:
        return {"trial_id": int(existing.iloc[0]["trial_id"]), "q_value": float(existing.iloc[0]["bh_q_value_global"]), "cached": True}
    hac = result["hac"]
    trial = {
        "trial_id": 71,
        "factor": RESEARCH_ID,
        "family": "industry_earnings_diffusion",
        "research_version": "V7_post_v6_preregistered",
        "primary_statistic": "historical_development_3m_industry_rank_ic_hac_t",
        **hac,
        "original_decision": decision,
        "post_v6_hypothesis": True,
        "evidence_scope": "historical_development",
    }
    ledger = pd.concat([ledger.drop(columns=["bh_q_value_global", "bh_fdr_5pct"], errors="ignore"), pd.DataFrame([trial])], ignore_index=True)
    ledger["bh_q_value_global"] = benjamini_hochberg(ledger["p_value_two_sided"])
    ledger["bh_fdr_5pct"] = ledger["bh_q_value_global"].le(0.05)
    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    return {"trial_id": 71, "q_value": float(ledger.iloc[-1]["bh_q_value_global"]), "cached": False}


def write_report(result: dict[str, Any], path: Path) -> None:
    stage_s_result = result["stage_s"]
    stage_p_result = result["stage_p"]
    audit = result["data_audit"]
    multiple_testing = result["multiple_testing"]
    lines = [
        "# F7 CSI1000行业盈利扩散研究报告",
        "",
        "## 1. 继承死亡边界",
        "",
        "V6的11月、前5行业价格动量轮动继续`REJECTED`；本研究不修改其结论或窗口。",
        "",
        "## 2. 新经济机制",
        "",
        "用PIT行业盈利改善广度和卖方一致预期上修衡量景气扩散；价格动量只作冻结增量控制。",
        "",
        "## 3. 产品角色",
        "",
        "候选角色为`BENCHMARK_SPECIFIC`，唯一主基准`000852.SH`；沪深300不参与晋级。",
        "",
        "## 4. 放宽项与补偿控制",
        "",
        "只放宽跨基准一致性；固定10%零净overlay、2%行业上限、TE门禁和12个月实时影子作为补偿。",
        "",
        "## 5. 事前冻结",
        "",
        f"registration SHA256=`{result['registration_sha256']}`；config SHA256=`{result['config_sha256']}`；唯一3个月期限、四组件等权、90日共识、trial 71。",
        "",
        "## 6. 数据与 PIT 审计",
        "",
        f"状态=`{audit['status']}`；财务{audit['financial_rows']:,}行，卖方预测{audit['report_rows']:,}行；覆盖={json.dumps(audit.get('coverage', {}), ensure_ascii=False)}。",
        f"manifest=`{audit.get('manifest_path')}`，SHA256=`{audit.get('manifest_sha256')}`；未来公告与重复键详见审计JSON。",
        "",
        "## 7. Stage S：信号评价",
        "",
        f"状态=`{stage_s_result['status']}`；3个月行业Rank IC={stage_s_result['mean_rank_ic_3m']:.6f}，正IC月占比={stage_s_result['positive_ic_month_share']:.2%}。",
        f"控制价格动量后的Partial IC={stage_s_result['price_momentum_partial_rank_ic']:.6f}；HAC t={stage_s_result['hac']['t_statistic']:.3f}，p={stage_s_result['hac']['p_value_two_sided']:.6g}。",
        f"年度={json.dumps(stage_s_result['annual_rank_ic'], ensure_ascii=False)}；组件={json.dumps(stage_s_result['component_rank_ic'], ensure_ascii=False)}；逐行业诊断{len(stage_s_result['industry_diagnostics'])}项。",
        f"门禁=`{json.dumps(stage_s_result['gates'], ensure_ascii=False)}`。",
        "",
        "## 8. Stage P：组合评价",
        "",
    ]
    if stage_p_result.get("status") in {"NOT_RUN", "FAILED"}:
        lines.append(f"Stage P状态：`{stage_p_result['status']}`；原因：{stage_p_result['reason']}。")
        if stage_p_result.get("message"):
            lines.append(f"失败诊断：`{stage_p_result['message']}`。")
    else:
        lines.extend(
            [
                f"- Delta IR={stage_p_result['delta_ir']:.6f}；年化净超额增量={stage_p_result['annual_net_excess_increment']:.2%}。",
                f"- TE增量={stage_p_result['tracking_error_increment']:.2%}；主动最大回撤变化={stage_p_result['active_max_drawdown_delta']:.2%}。",
                f"- 最大行业累计主动贡献占比={stage_p_result['maximum_industry_contribution']:.2%}；门禁：`{json.dumps(stage_p_result['gates'], ensure_ascii=False)}`。",
                f"- 单月最大缺失收益持仓权重={stage_p_result['maximum_missing_return_weight']:.2%}，按冻结基线规则以-100%保守计价。",
            ]
        )
    lines.extend(
        [
            "",
            "## 9. 相对 Lane A 的边际贡献",
            "",
            (
                f"Delta IR={stage_p_result['delta_ir']:.6f}，年化净超额增量={stage_p_result['annual_net_excess_increment']:.2%}。"
                if "delta_ir" in stage_p_result
                else "Stage S未通过或组合映射失败，未声称相对Lane A存在边际贡献。"
            ),
            "",
            "## 10. 容量、成本和集中度",
            "",
            (
                f"容量={json.dumps(stage_p_result['capacity'], ensure_ascii=False)}；最大行业贡献={stage_p_result['maximum_industry_contribution']:.2%}；成本压力={json.dumps(stage_p_result['cost_stress'], ensure_ascii=False)}。"
                if "capacity" in stage_p_result
                else "Stage P未运行；容量、成本压力和贡献集中度不作通过性结论。"
            ),
            "",
            "## 11. 多重检验",
            "",
            f"trial_id={multiple_testing['trial_id']}；全局BH q={multiple_testing['q_value']:.6g}；历史p值仅属开发证据。",
            "",
            "## 12. 历史诊断与实时确认边界",
            "",
            "2018-07至2026-06只作development；历史通过最多`RESEARCH_SHADOW`，正式确认需2026-07后12个月append-only记录。",
            "",
            "## 13. 决策",
            "",
            f"最终历史决策：`{result['decision']}`。",
            "",
            "## 14. Kill / Continue 条件",
            "",
            (
                "进入12个月实时影子；Delta IR<=0、单行业主导、容量/约束失败或实时未确认即kill。"
                if result["decision"] == "RESEARCH_SHADOW"
                else "当前构造停止；不得翻号、换基准或删除失败年份后重跑。"
            ),
            "",
            "## 15. 可复算命令、manifest、commit、config hash",
            "",
            "复算：`python -m scripts.v7.run_industry_earnings_diffusion_v7`。",
            f"manifest=`{audit.get('manifest_path')}`；commit=`{result.get('workspace_commit', 'UNAVAILABLE')}`；config SHA256=`{result['config_sha256']}`。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--backfill-dir", type=Path, default=Path("artifacts/data_backfill_v7/f7_financials"))
    parser.add_argument("--evaluation-dir", type=Path, default=Path("artifacts/evaluations"))
    parser.add_argument("--audit-dir", type=Path, default=Path("artifacts/data_audits"))
    args = parser.parse_args()
    validate_registration(REGISTRATION_CONFIG)
    tushare_dir = args.artifact_dir / "tushare"
    index_weights = pd.read_parquet(tushare_dir / "index_weight_000852_SH.parquet")
    expected_symbols = index_weights["con_code"].nunique()
    expected_months = {period.strftime("%Y%m") for period in pd.period_range("2018-04", "2026-07", freq="M")}
    backfill = require_complete_backfill(args.backfill_dir, expected_symbols, expected_months)
    financial = load_verified_shards(backfill["financial_paths"])
    reports = load_verified_shards(backfill["report_paths"])
    raw_quality = raw_data_quality(financial, reports)
    baseline_monthly = pd.read_parquet(args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet")
    baseline_monthly = baseline_monthly[baseline_monthly["index_code"].eq("000852.SH")]
    signal_dates = sorted(pd.to_datetime(baseline_monthly["signal_date"].unique()))
    selected_index_weights = index_weights[
        index_weights["trade_date"].astype(str).isin({date.strftime("%Y%m%d") for date in signal_dates})
    ]
    members = build_csi1000_member_panel(
        selected_index_weights,
        pd.read_parquet(tushare_dir / "index_members_sw2021.parquet"),
        pd.read_parquet(tushare_dir / "daily_basic_month_end.parquet"),
    )
    stock_basic_path = tushare_dir / "stock_basic.parquet"
    stock_st_path = tushare_dir / "stock_st_month_end.parquet"
    adv20_path = args.artifact_dir / "adv20_capacity_v5.parquet"
    labels = prepare_execution_labels(
        pd.read_parquet(args.artifact_dir / "portfolio_execution_labels_v5.parquet"),
        pd.read_parquet(stock_basic_path),
        pd.read_parquet(stock_st_path),
        pd.read_parquet(adv20_path),
    )
    financial_signal = financial_acceleration_pit(financial, signal_dates)
    analyst_signal = analyst_revision_pit(reports, signal_dates)
    scores = aggregate_industry_diffusion(members, financial_signal, analyst_signal)
    coverage_monthly, coverage = coverage_audit(scores)
    future = forward_industry_returns(members, labels)
    one_month = one_month_industry_returns(members, labels)
    momentum, momentum_audit = build_industry_momentum_scores(one_month.dropna(subset=["industry_return", "exit_date"]), history_months=11)
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_data_manifest(backfill["financial_paths"], backfill["report_paths"])
    manifest["sources"] = {
        "registration": sha256_file(REGISTRATION),
        "index_weight": sha256_file(tushare_dir / "index_weight_000852_SH.parquet"),
        "industry_members": sha256_file(tushare_dir / "index_members_sw2021.parquet"),
        "market_caps": sha256_file(tushare_dir / "daily_basic_month_end.parquet"),
        "execution_labels": sha256_file(args.artifact_dir / "portfolio_execution_labels_v5.parquet"),
        "stock_basic": sha256_file(stock_basic_path),
        "stock_st_month_end": sha256_file(stock_st_path),
        "baseline_monthly": sha256_file(args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"),
        "baseline_holdings": sha256_file(args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_holdings.parquet"),
        "adv20": sha256_file(adv20_path),
    }
    manifest_path = args.audit_dir / "f7_industry_earnings_diffusion_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    audit = {
        "version": 7,
        "research_id": RESEARCH_ID,
        "status": "PASS" if coverage["passes"] else "DATA_BLOCKED",
        "registration_sha256": sha256_file(REGISTRATION),
        "config_sha256": config_sha256(),
        "financial_rows": len(financial),
        "report_rows": len(reports),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "raw_data_quality": raw_quality,
        "member_rows": len(members),
        "expected_member_rows": len(selected_index_weights),
        "pit_industry_member_coverage": float(len(members) / len(selected_index_weights)),
        "market_cap_coverage": float(members["total_mv"].notna().mean()),
        "member_months": members["signal_date"].nunique(),
        "duplicate_member_keys": int(members.duplicated(["signal_date", "ts_code"]).sum()),
        "financial_future_violations": int(financial_signal["ann_date"].gt(financial_signal["signal_date"]).sum()),
        "report_future_violations": int(
            analyst_signal["latest_report_date"].gt(analyst_signal["signal_date"]).sum()
            + analyst_signal["previous_latest_report_date"].gt(analyst_signal["previous_as_of_date"]).sum()
        ),
        "coverage": coverage,
        "component_coverage_extrema": {
            "minimum_revenue_companies": int(scores["revenue_acceleration_companies"].min()),
            "minimum_deducted_profit_companies": int(scores["deducted_profit_acceleration_companies"].min()),
            "minimum_roe_companies": int(scores["roe_improvement_companies"].min()),
            "minimum_revision_companies": int(scores["earnings_revision_companies"].min()),
            "minimum_revision_market_cap_coverage": float(scores["earnings_revision_market_cap_coverage"].min()),
        },
        "sources": manifest["sources"],
    }
    if (
        audit["duplicate_member_keys"]
        or audit["financial_future_violations"]
        or audit["report_future_violations"]
        or raw_quality["financial_exact_duplicate_rows"]
        or raw_quality["report_exact_duplicate_rows"]
        or audit["pit_industry_member_coverage"] < 0.98
        or audit["market_cap_coverage"] < 0.98
    ):
        audit["status"] = "DATA_BLOCKED"
    (args.audit_dir / "f7_industry_earnings_diffusion.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    args.evaluation_dir.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(args.evaluation_dir / "f7_industry_earnings_diffusion_signals.parquet", index=False)
    coverage_monthly.to_parquet(args.evaluation_dir / "f7_industry_earnings_diffusion_coverage.parquet", index=False)
    momentum_audit.to_parquet(args.evaluation_dir / "f7_industry_earnings_diffusion_momentum_audit.parquet", index=False)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: F7 coverage/PIT audit failed")
    valid_dates = set(coverage_monthly.loc[coverage_monthly["month_pass"], "signal_date"])
    signal_result = stage_s(scores, future, momentum, valid_dates)
    signal_status = "SIGNAL_VALID" if signal_result["gates"]["passes_all"] else "REJECTED"
    if can_run_stage_p(signal_status):
        baseline_holdings = pd.read_parquet(args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_holdings.parquet")
        baseline_holdings = baseline_holdings[baseline_holdings["index_code"].eq("000852.SH")]
        portfolio_scores = scores.copy()
        portfolio_scores.loc[
            ~portfolio_scores["signal_date"].isin(valid_dates),
            "industry_earnings_diffusion",
        ] = np.nan
        try:
            candidate, holdings, contributions = build_overlay_portfolio(portfolio_scores, members, labels, baseline_monthly, baseline_holdings)
            portfolio_result = stage_p(candidate, holdings, contributions, baseline_monthly, adv20_path)
            decision = "RESEARCH_SHADOW" if portfolio_result["gates"]["passes_all"] else "REJECTED"
            candidate.to_parquet(args.evaluation_dir / "f7_industry_earnings_diffusion_monthly.parquet", index=False)
            holdings.to_parquet(args.evaluation_dir / "f7_industry_earnings_diffusion_holdings.parquet", index=False)
        except ValueError as exc:
            portfolio_result = {
                "status": "FAILED",
                "reason": "registered portfolio mapping or execution constraint failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "gates": {"passes_all": False},
            }
            decision = "REJECTED"
    else:
        portfolio_result = {"status": "NOT_RUN", "reason": "Stage S failed"}
        decision = "REJECTED"
    validate_research_decision(
        decision,
        evidence_scope="historical_development",
        live_observations=0,
        required_live_observations=12,
    )
    ledger = update_ledger(signal_result, decision, args.evaluation_dir / "multiple_testing_ledger_v7.csv")
    result = {"research_id": RESEARCH_ID, "registration_sha256": sha256_file(REGISTRATION), "config_sha256": config_sha256(), "workspace_commit": "UNAVAILABLE_NO_GIT", "data_audit": audit, "stage_s": {**signal_result, "status": signal_status}, "stage_p": portfolio_result, "multiple_testing": ledger, "decision": decision, "historical_evidence_scope": "development_only"}
    (args.evaluation_dir / "f7_industry_earnings_diffusion_evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_report(result, args.evaluation_dir / "f7_industry_earnings_diffusion_report.md")
    if decision == "RESEARCH_SHADOW":
        shadow_dir = Path("artifacts/live_shadow_v7/f7_industry_earnings_diffusion")
        shadow_dir.mkdir(parents=True, exist_ok=True)
        config_path = shadow_dir / "config.json"
        if not config_path.exists():
            config_path.write_text(
                json.dumps(
                    {
                        "research_id": RESEARCH_ID,
                        "registration_sha256": result["registration_sha256"],
                        "config_sha256": result["config_sha256"],
                        "append_only": True,
                        "minimum_live_months": 12,
                        "observations": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    print(json.dumps({"research_id": RESEARCH_ID, "decision": decision, "stage_s": signal_result["gates"], "stage_p": portfolio_result.get("gates")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
