"""Evaluate frozen P0 holdings against the CNY 10m and 5% ADV20 assumption."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def summarize(frame: pd.DataFrame, capital: float, participation_cap: float) -> dict:
    trades = frame[frame["trade_weight"].abs().gt(1e-14)].copy()
    trades["trade_amount_cny"] = trades["trade_weight"].abs() * capital
    trades["participation"] = trades["trade_amount_cny"] / trades["adv20_cny"]
    valid = trades[trades["adv20_cny"].gt(0)]
    capacity = participation_cap * valid["adv20_cny"] / valid["trade_weight"].abs()
    return {
        "trades": int(len(trades)),
        "trades_missing_adv20": int(trades["adv20_cny"].isna().sum()),
        "maximum_participation": float(valid["participation"].max()),
        "p95_participation": float(valid["participation"].quantile(0.95)),
        "trades_above_participation_cap": int(
            valid["participation"].gt(participation_cap + 1e-12).sum()
        ),
        "minimum_capacity_at_cap_cny": float(capacity.min()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    parser.add_argument("--capital", type=float, default=10_000_000)
    parser.add_argument("--participation-cap", type=float, default=0.05)
    parser.add_argument("--stem", default="style_baseline_portfolio_v5")
    args = parser.parse_args()
    holdings = pd.read_parquet(args.artifact_dir / f"{args.stem}_holdings.parquet")
    adv = pd.read_parquet(args.artifact_dir / "adv20_capacity_v5.parquet")
    frame = holdings.merge(adv, on=["ts_code", "signal_date"], how="left", validate="many_to_one")
    reports = {}
    for index_code, group in frame.groupby("index_code"):
        reports[index_code] = {
            "full": summarize(group, args.capital, args.participation_cap),
            "fixed_validation": summarize(
                group[group["signal_date"].ge("2023-07-01")],
                args.capital,
                args.participation_cap,
            ),
        }
    payload = {
        "capital_cny": args.capital,
        "participation_cap": args.participation_cap,
        "benchmarks": reports,
    }
    output = args.artifact_dir / f"{args.stem}_capacity.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
