"""Evaluate the result-before-frozen 15%/60-day volatility target."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_v5 import performance_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/alpha_phase1"))
    args = parser.parse_args()
    base = pd.read_parquet(
        args.artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"
    )
    parts = []
    reports = {}
    for index_code, group in base.groupby("index_code"):
        daily = pd.read_parquet(
            args.artifact_dir
            / "tushare"
            / f"index_daily_{index_code.replace('.', '_')}.parquet"
        )
        daily["date"] = pd.to_datetime(daily["trade_date"], format="%Y%m%d")
        daily = daily.sort_values("date")
        daily["daily_return"] = daily["close"].pct_change()
        daily["realized_volatility_60d"] = (
            daily["daily_return"].rolling(60, min_periods=40).std(ddof=1) * np.sqrt(252)
        )
        signals = group[["signal_date"]].sort_values("signal_date")
        risk = pd.merge_asof(
            signals,
            daily[["date", "realized_volatility_60d"]],
            left_on="signal_date",
            right_on="date",
            direction="backward",
        )
        risk["equity_exposure"] = (
            0.15 / risk["realized_volatility_60d"]
        ).clip(lower=0.50, upper=1.0).fillna(1.0)
        overlay = group.merge(
            risk[["signal_date", "realized_volatility_60d", "equity_exposure"]],
            on="signal_date",
            validate="one_to_one",
        )
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
            "construction": {
                "name": "15pct_60d_realized_volatility_target",
                "target_annual_volatility": 0.15,
                "lookback_trading_days": 60,
                "minimum_observations": 40,
                "minimum_equity_exposure": 0.50,
            },
            "full": performance_metrics(overlay),
            "train": performance_metrics(train),
            "fixed_validation": performance_metrics(validation),
            "average_equity_exposure": float(overlay["equity_exposure"].mean()),
            "minimum_equity_exposure_realized": float(overlay["equity_exposure"].min()),
        }
        parts.append(overlay)
    pd.concat(parts, ignore_index=True).to_parquet(
        args.artifact_dir / "style_rolling_regression_vol_target_v5_monthly.parquet",
        index=False,
    )
    output = args.artifact_dir / "style_rolling_regression_vol_target_v5_evaluation.json"
    output.write_text(
        json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"benchmarks": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
