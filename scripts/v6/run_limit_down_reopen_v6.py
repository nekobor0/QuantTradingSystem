"""Run the preregistered Lane D limit-down reopening event study."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.short_horizon import calculate_short_signals
from quant_trading_system.research.alpha_phase1.tdx_raw import parse_research_series
from quant_trading_system.research.v6.bottom_reversal import (
    attach_pit_survival,
    detect_limit_down_reopen,
)
from scripts.alpha_phase1.build_multiple_testing_ledger_v5 import benjamini_hochberg
from scripts.alpha_phase1.run_style_baseline_portfolio_v5 import prepare_panel
from scripts.v6.update_multiple_testing_v6 import block_bootstrap_mean, hac_mean_test


RESEARCH_ID = "limit_down_reopen_survival_v6"
HORIZONS = (1, 3, 5, 10, 20)
VALIDATION_START = pd.Timestamp("2023-07-01")
VALIDATION_END = pd.Timestamp("2026-06-30")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def market_horizon_returns(panel_path: Path) -> dict[int, pd.Series]:
    result: dict[int, pd.Series] = {}
    for horizon in HORIZONS:
        columns = [
            "signal_date", f"forward_return_{horizon}",
            f"entry_tradable_{horizon}", f"exit_tradable_{horizon}",
        ]
        panel = pd.read_parquet(panel_path, columns=columns)
        panel["signal_date"] = pd.to_datetime(panel["signal_date"])
        valid = panel[f"entry_tradable_{horizon}"] & panel[f"exit_tradable_{horizon}"]
        result[horizon] = panel.loc[valid].groupby("signal_date")[f"forward_return_{horizon}"].mean()
    return result


def build_events(
    *,
    raw_dir: Path,
    raw_audit_path: Path,
    limits_path: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    audit = json.loads(raw_audit_path.read_text(encoding="utf-8"))
    by_file: dict[str, list[str]] = defaultdict(list)
    for symbol, details in audit["selected"].items():
        by_file[str(details["file"])].append(symbol)
    limits = pd.read_parquet(
        limits_path, columns=["ts_code", "trade_date", "down_limit"]
    )
    limits["date"] = pd.to_datetime(limits.pop("trade_date"), format="%Y%m%d")
    limits = limits[limits["date"].le(VALIDATION_END + pd.Timedelta(days=31))]
    limits = limits.set_index(["ts_code", "date"]).sort_index()
    limit_symbols = set(limits.index.get_level_values("ts_code").unique())
    print(
        json.dumps(
            {
                "event": "limits_loaded",
                "rows": len(limits),
                "symbols": len(limit_symbols),
            }
        ),
        flush=True,
    )
    rows: list[dict[str, object]] = []
    parsed_symbols = 0
    for file_number, (filename, symbols) in enumerate(sorted(by_file.items()), start=1):
        payload = json.loads((raw_dir / filename).read_text(encoding="utf-8"))
        available = {series.symbol: series for series in parse_research_series(payload)}
        for symbol in symbols:
            series = available.get(symbol)
            if series is None or symbol not in limit_symbols:
                continue
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(series.dates),
                    "open": series.open,
                    "high": series.high,
                    "low": series.low,
                    "close": series.close,
                    "volume": series.volume,
                    "amount_wan": series.amount_wan,
                    "factor": series.forward_factor,
                }
            ).set_index("date")
            stock_limits = limits.xs(symbol, level="ts_code")
            frame = frame.join(stock_limits, how="left")
            event_mask = detect_limit_down_reopen(frame)
            if event_mask.any():
                labels = calculate_short_signals(frame.reset_index())
                for date in frame.index[event_mask]:
                    event = {
                        "ts_code": symbol,
                        "signal_date": date,
                        "open": float(frame.at[date, "open"]),
                        "high": float(frame.at[date, "high"]),
                        "low": float(frame.at[date, "low"]),
                        "close": float(frame.at[date, "close"]),
                        "down_limit": float(frame.at[date, "down_limit"]),
                        "event_amount_cny": float(frame.at[date, "amount_wan"] * 10_000),
                    }
                    for horizon in HORIZONS:
                        event[f"forward_return_{horizon}"] = labels.at[
                            date, f"forward_return_{horizon}"
                        ]
                        event[f"entry_tradable_{horizon}"] = bool(
                            labels.at[date, f"entry_tradable_{horizon}"]
                        )
                        event[f"exit_tradable_{horizon}"] = bool(
                            labels.at[date, f"exit_tradable_{horizon}"]
                        )
                    rows.append(event)
            parsed_symbols += 1
        if file_number % 500 == 0:
            print(json.dumps({"event": "raw_progress", "files": file_number, "symbols": parsed_symbols, "events": len(rows)}), flush=True)
    return pd.DataFrame(rows), {
        "selected_symbols": len(audit["selected"]),
        "parsed_symbols": parsed_symbols,
        "source_files": len(by_file),
        "raw_event_count": len(rows),
    }


def evaluate_window(events: pd.DataFrame, horizon: int, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, object]:
    valid = events[
        events["signal_date"].between(start, end)
        & events[f"entry_tradable_{horizon}"]
        & events[f"exit_tradable_{horizon}"]
        & events[f"forward_return_{horizon}"].notna()
        & events[f"market_return_{horizon}"].notna()
    ].copy()
    valid["net_car"] = (
        valid[f"forward_return_{horizon}"] - valid[f"market_return_{horizon}"] - 0.002
    )
    daily = valid.groupby("signal_date", sort=True)["net_car"].mean()
    hac = hac_mean_test(daily) if len(daily) >= 2 else None
    bootstrap = block_bootstrap_mean(daily, seed=9 + horizon) if len(daily) >= 2 else None
    return {
        "events": int(len(valid)),
        "event_days": int(len(daily)),
        "mean_net_car": float(valid["net_car"].mean()) if len(valid) else None,
        "median_net_car": float(valid["net_car"].median()) if len(valid) else None,
        "positive_rate": float(valid["net_car"].gt(0).mean()) if len(valid) else None,
        "worst_event": float(valid["net_car"].min()) if len(valid) else None,
        "hac": hac,
        "bootstrap": bootstrap,
    }


def update_ledger(core: dict[str, object], decision: str, output_dir: Path) -> dict[str, object] | None:
    if core["hac"] is None:
        return None
    ledger_path = output_dir / "multiple_testing_ledger_v6.csv"
    ledger = pd.read_csv(ledger_path)
    ledger = ledger[ledger["factor"].ne(RESEARCH_ID)].copy()
    trial = {
        "trial_id": int(ledger["trial_id"].max()) + 1,
        "factor": RESEARCH_ID,
        "family": "bottom_reversal_limit_down_reopen",
        "research_version": "V6_preregistered",
        "primary_statistic": "fixed_validation_10d_matched_net_car_hac_t",
        **core["hac"],
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
    parser.add_argument("--raw-dir", type=Path, default=Path("artifacts/tdx_bridge/raw"))
    parser.add_argument("--raw-audit", type=Path, default=Path("artifacts/alpha_phase1/tdx_research_raw_audit.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluations"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw_events, source = build_events(
        raw_dir=args.raw_dir,
        raw_audit_path=args.raw_audit,
        limits_path=args.artifact_dir / "tushare" / "stk_limit_full.parquet",
    )
    if raw_events.empty:
        raise SystemExit("DATA_BLOCKED: no raw limit-down reopening events")
    fundamentals = prepare_panel(args.artifact_dir)[
        ["ts_code", "signal_date", "baseline_quality_z", "is_st", "delist_date", "l1_code"]
    ].copy()
    events = attach_pit_survival(raw_events, fundamentals)
    events = events[events["pit_survival"]].copy()
    market = market_horizon_returns(args.artifact_dir / "factor_panel_short_horizon_v4_t1_open.parquet")
    for horizon, returns in market.items():
        events[f"market_return_{horizon}"] = events["signal_date"].map(returns)
    events.to_parquet(args.output_dir / f"{RESEARCH_ID}_events.parquet", index=False)
    audit = {
        "version": 6,
        "research_id": RESEARCH_ID,
        "status": "PASS",
        "source_summary": source,
        "survival_events": int(len(events)),
        "symbols": int(events["ts_code"].nunique()),
        "date_start": events["signal_date"].min().date().isoformat(),
        "date_end": events["signal_date"].max().date().isoformat(),
        "duplicate_keys": int(events.duplicated(["ts_code", "signal_date"]).sum()),
        "future_information_violations": int(events["fundamental_date"].gt(events["signal_date"]).sum()),
        "sources": {
            "raw_audit": sha256_file(args.raw_audit),
            "limits": sha256_file(args.artifact_dir / "tushare" / "stk_limit_full.parquet"),
            "fundamental_panel": sha256_file(args.artifact_dir / "factor_panel_style_baseline_v5.parquet"),
            "registration": sha256_file(Path("artifacts/registrations/limit_down_reopen_survival_v6.md")),
        },
    }
    if audit["duplicate_keys"] or audit["future_information_violations"]:
        audit["status"] = "DATA_BLOCKED"
    audit_path = Path("artifacts/data_audits/limit_down_reopen_survival_v6.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "data_audit", **audit}, ensure_ascii=False), flush=True)
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: event audit failed")

    development = {
        str(h): evaluate_window(events, h, pd.Timestamp("2018-07-02"), pd.Timestamp("2023-06-30"))
        for h in HORIZONS
    }
    validation = {str(h): evaluate_window(events, h, VALIDATION_START, VALIDATION_END) for h in HORIZONS}
    core = validation["10"]
    core_events = events[
        events["signal_date"].between(VALIDATION_START, VALIDATION_END)
        & events["entry_tradable_10"]
        & events["exit_tradable_10"]
        & events["forward_return_10"].notna()
        & events["market_return_10"].notna()
    ].copy()
    core_events["net_car"] = core_events["forward_return_10"] - core_events["market_return_10"] - 0.002
    total = float(core_events["net_car"].sum())
    by_stock = core_events.groupby("ts_code")["net_car"].sum()
    maximum_stock_share = float(by_stock.max() / total) if total > 0 and len(by_stock) else None
    minimum_capacity = float((core_events["event_amount_cny"] * 0.05).min()) if len(core_events) else 0.0
    gates = {
        "events_at_least_30": core["events"] >= 30,
        "mean_net_car_gt_002": core["mean_net_car"] is not None and core["mean_net_car"] > 0.02,
        "positive_rate_gt_055": core["positive_rate"] is not None and core["positive_rate"] > 0.55,
        "hac_t_gt_1": core["hac"] is not None and core["hac"]["t_statistic"] > 1.0,
        "bootstrap_lower_gt_0": core["bootstrap"] is not None and core["bootstrap"]["ci_2_5pct"] > 0,
        "worst_event_gt_minus_030": core["worst_event"] is not None and core["worst_event"] > -0.30,
        "single_stock_contribution_at_most_020": maximum_stock_share is not None and maximum_stock_share <= 0.20,
        "capacity_1m_pass": minimum_capacity >= 1_000_000,
    }
    gates["passes_all_registered_gates"] = all(gates.values())
    decision = (
        "DATA_BLOCKED" if core["events"] < 30 else
        "PROMOTE_TO_LIVE_SHADOW" if gates["passes_all_registered_gates"] else "REJECTED"
    )
    ledger = update_ledger(core, decision, args.output_dir)
    result = {
        "research_id": RESEARCH_ID,
        "registration_sha256": sha256_file(Path("artifacts/registrations/limit_down_reopen_survival_v6.md")),
        "data_audit": audit,
        "development": development,
        "fixed_validation": validation,
        "core_diagnostics": {
            "minimum_capacity_at_5pct_cny": minimum_capacity,
            "maximum_stock_contribution_share": maximum_stock_share,
            "events_by_year": {str(k): int(v) for k, v in core_events.groupby(core_events["signal_date"].dt.year).size().items()},
            "events_by_industry": {str(k): int(v) for k, v in core_events.groupby("l1_code").size().sort_values(ascending=False).items()},
        },
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
