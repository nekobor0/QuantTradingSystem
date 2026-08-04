"""Build frozen quarterly PIT styles and fundamental-surprise candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.alpha_phase1.fundamental_surprise import (
    announcement_returns,
    grouped_standardize,
    monthly_point_in_time,
    prepare_versions,
    residualize_surprise,
)


HYPOTHESES = {
    "profit_acceleration_underreaction_v4": "A股财报季中利润增长加速但公告后价格反应不足的公司，信息会在随后三个月继续扩散。",
    "sales_profit_breadth_underreaction_v4": "营收和利润同时加速且价格尚未充分反应，比单一利润变化更可靠，随后三个月收益更高。",
    "cash_confirmed_profit_underreaction_v4": "利润加速同时得到经营现金流收入比改善确认且价格反应不足时，随后三个月收益更高。",
}


def _raw_prices(raw_dir: Path, symbol: str, details: dict[str, object]) -> pd.Series:
    payload = json.loads((raw_dir / str(details["file"])).read_text(encoding="utf-8"))
    series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
    return pd.Series(
        np.asarray(series.close) * np.asarray(series.forward_factor),
        index=pd.to_datetime(series.dates),
    )


def _delisted_prices(tushare_dir: Path) -> dict[str, pd.Series]:
    daily = pd.read_parquet(tushare_dir / "delisted_daily.parquet")
    factors = pd.read_parquet(tushare_dir / "delisted_adj_factor.parquet")
    merged = daily.merge(factors, on=["ts_code", "trade_date"], how="inner", validate="one_to_one")
    output = {}
    for symbol, group in merged.groupby("ts_code", sort=True):
        output[str(symbol)] = pd.Series(
            group["close"].to_numpy() * group["adj_factor"].to_numpy(),
            index=pd.to_datetime(group["trade_date"].astype(str)),
        ).sort_index()
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fina-indicator", type=Path, required=True)
    parser.add_argument("--style-panel", type=Path, required=True)
    parser.add_argument("--slow-labels", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    styles = pd.read_parquet(args.style_panel)
    styles["signal_date"] = pd.to_datetime(styles["signal_date"])
    signal_dates = sorted(pd.Timestamp(value) for value in styles["signal_date"].unique())
    versions = prepare_versions(pd.read_parquet(args.fina_indicator))
    monthly = monthly_point_in_time(versions, signal_dates)
    monthly["report_age_days"] = (monthly["signal_date"] - monthly["ann_date"]).dt.days
    monthly = monthly[monthly["report_age_days"].between(0, 120)]
    keys = ["ts_code", "signal_date"]
    frame = styles.merge(monthly, on=keys, how="left", validate="one_to_one")
    labels = pd.read_parquet(args.slow_labels)
    labels["signal_date"] = pd.to_datetime(labels["signal_date"])
    frame = frame.merge(labels, on=keys, how="left", validate="one_to_one")

    frame["announcement_return"] = np.nan
    selected = json.loads(args.tdx_audit.read_text(encoding="utf-8"))["selected"]
    delisted = _delisted_prices(args.tushare_dir)
    for number, (symbol, indices) in enumerate(frame.groupby("ts_code", sort=True).groups.items(), start=1):
        if frame.loc[indices, "ann_date"].notna().sum() == 0:
            continue
        if symbol in selected:
            prices = _raw_prices(args.tdx_raw, symbol, selected[symbol])
        elif symbol in delisted:
            prices = delisted[symbol]
        else:
            continue
        frame.loc[indices, "announcement_return"] = announcement_returns(
            prices, frame.loc[indices, "ann_date"], frame.loc[indices, "signal_date"]
        )
        if number % 500 == 0:
            print(json.dumps({"event": "reaction_progress", "symbols": number}), flush=True)

    frame["standardization_group"] = np.where(
        frame["financial_sector"].eq("nonfinancial"), frame["l1_code"], frame["financial_sector"]
    )
    raw_to_z = {
        "q_profit_yoy_acceleration": "profit_acceleration_z",
        "q_sales_yoy_acceleration": "sales_acceleration_z",
        "ocf_to_or_acceleration": "cash_confirmation_z",
        "roe_waa": "quality_roe_z",
        "grossprofit_margin": "quality_gross_margin_z",
        "netprofit_margin": "quality_net_margin_z",
        "ocf_to_or": "quality_cash_to_revenue_z",
        "debt_to_assets": "leverage",
    }
    frame[list(raw_to_z.values())] = np.nan
    for _, indices in frame.groupby("signal_date", sort=False).groups.items():
        for source, target in raw_to_z.items():
            frame.loc[indices, target] = grouped_standardize(
                frame.loc[indices, source], frame.loc[indices, "standardization_group"]
            )

    quality_columns = [
        "quality_roe_z", "quality_gross_margin_z", "quality_net_margin_z",
        "quality_cash_to_revenue_z",
    ]
    frame["quality_composite"] = frame[quality_columns].mean(axis=1).where(
        frame[quality_columns].notna().sum(axis=1) >= 2
    )
    profit = frame["profit_acceleration_z"]
    breadth = pd.concat([profit, frame["sales_acceleration_z"]], axis=1).min(axis=1).where(
        profit.notna() & frame["sales_acceleration_z"].notna()
    )
    cash_confirmed = pd.concat([profit, frame["cash_confirmation_z"]], axis=1).mean(axis=1).where(
        profit.notna() & frame["cash_confirmation_z"].notna()
    )
    frame["profit_acceleration_underreaction_v4"] = residualize_surprise(frame, profit)
    frame["sales_profit_breadth_underreaction_v4"] = residualize_surprise(frame, breadth)
    frame["cash_confirmed_profit_underreaction_v4"] = residualize_surprise(frame, cash_confirmed)

    output_columns = [
        *keys, "ann_date", "end_date", "report_age_days", "announcement_return",
        "q_profit_yoy_acceleration", "q_sales_yoy_acceleration", "ocf_to_or_acceleration",
        "grossprofit_margin", "quality_composite", "leverage", *HYPOTHESES,
        "forward_return_1m", "forward_return_3m", "forward_return_6m", "forward_return_12m",
        "entry_tradable", "exit_3m_tradable",
    ]
    output = frame[output_columns].sort_values(keys)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    active = frame[frame["size"].notna()]
    payload = {
        "version": 4,
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(keys).sum()),
        "factor_hypotheses": HYPOTHESES,
        "active_coverage": {
            column: float(active[column].notna().mean())
            for column in ["quality_composite", "leverage", *HYPOTHESES]
        },
        "protocol": "quarterly PIT by ann_date; latest then-visible version; <=120-day signal age; T+1 adjusted open, 3-month core exit",
        "gross_margin_naming": "grossprofit_margin is stored as gross margin and is never named gross_profitability",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
