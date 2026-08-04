"""Evaluate the single result-before-frozen MA200/70% risk overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import performance_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    args = parser.parse_args()
    base = pd.read_parquet(args.artifact_dir / "style_baseline_portfolio_v5_monthly.parquet")
    parts = []
    reports = {}
    for index_code, group in base.groupby("index_code"):
        daily = pd.read_parquet(
            args.artifact_dir / "tushare" / f"index_daily_{index_code.replace('.', '_')}.parquet"
        )
        daily["date"] = pd.to_datetime(daily["trade_date"], format="%Y%m%d")
        daily = daily.sort_values("date")
        daily["ma200"] = daily["close"].rolling(200, min_periods=200).mean()
        signals = group[["signal_date"]].sort_values("signal_date")
        regime = pd.merge_asof(
            signals,
            daily[["date", "close", "ma200"]],
            left_on="signal_date",
            right_on="date",
            direction="backward",
        )
        regime["equity_exposure"] = regime["close"].ge(regime["ma200"]).map({True: 1.0, False: 0.70})
        overlay = group.merge(regime[["signal_date", "equity_exposure"]], on="signal_date", validate="one_to_one")
        previous_exposure = overlay["equity_exposure"].shift().fillna(0.0)
        overlay["turnover"] = (
            overlay["equity_exposure"] * overlay["turnover"]
            + (overlay["equity_exposure"] - previous_exposure).abs()
        )
        overlay["portfolio_net_return"] = (
            overlay["equity_exposure"] * overlay["portfolio_gross_return"]
            - overlay["turnover"] * 0.0005
        )
        train = overlay[overlay["signal_date"].le("2023-06-30")]
        validation = overlay[overlay["signal_date"].ge("2023-07-01")]
        reports[index_code] = {
            "full": performance_metrics(overlay),
            "train": performance_metrics(train),
            "fixed_validation": performance_metrics(validation),
            "months_at_70pct": int(overlay["equity_exposure"].eq(0.70).sum()),
        }
        parts.append(overlay)
    pd.concat(parts, ignore_index=True).to_parquet(
        args.artifact_dir / "style_baseline_risk_overlay_v5_monthly.parquet", index=False
    )
    output = args.artifact_dir / "style_baseline_risk_overlay_v5_evaluation.json"
    output.write_text(json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
