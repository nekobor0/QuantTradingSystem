"""Build an existing-data ADV20 proxy for the frozen CNY 10m capacity check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    args = parser.parse_args()
    source = pd.read_parquet(
        args.artifact_dir / "tushare" / "daily_basic_full.parquet",
        columns=["ts_code", "trade_date", "close", "free_share", "turnover_rate_f"],
    )
    source["date"] = pd.to_datetime(source["trade_date"], format="%Y%m%d")
    source = source.sort_values(["ts_code", "date"])
    source["daily_amount_proxy_cny"] = (
        source["close"] * source["free_share"] * 10_000 * source["turnover_rate_f"] / 100
    )
    source["adv20_cny"] = (
        source.groupby("ts_code", sort=False)["daily_amount_proxy_cny"]
        .rolling(20, min_periods=10)
        .mean()
        .reset_index(level=0, drop=True)
    )
    labels = pd.read_parquet(
        args.artifact_dir / "portfolio_execution_labels_v5.parquet",
        columns=["ts_code", "signal_date", "entry_date"],
    )
    output = labels.merge(
        source[["ts_code", "date", "adv20_cny"]],
        left_on=["ts_code", "entry_date"],
        right_on=["ts_code", "date"],
        how="left",
        validate="one_to_one",
    ).drop(columns=["date"])
    path = args.artifact_dir / "adv20_capacity_v5.parquet"
    temporary = path.with_suffix(path.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)
    active = output[output["entry_date"].notna()]
    payload = {
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(["ts_code", "signal_date"]).sum()),
        "dated_coverage": float(active["adv20_cny"].notna().mean()),
        "protocol": "ADV20 proxy = 20-day mean(close * free_share * 10000 * turnover_rate_f / 100), minimum 10 days",
        "capacity": "CNY 10m; flag absolute trade amount above 5% ADV20",
    }
    metadata = args.artifact_dir / "adv20_capacity_v5_metadata.json"
    metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
