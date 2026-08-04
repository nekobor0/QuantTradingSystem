"""Build the frozen V4 extended style baseline without relabeling returns."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.alpha_phase1.long_only_evaluation import industry_panel
from quant_trading_system.research.alpha_phase1.style_baseline import (
    add_cross_sectional_styles,
    rolling_beta_and_residual_volatility,
)


def _raw_return(raw_dir: Path, symbol: str, details: dict[str, object]) -> pd.Series:
    payload = json.loads((raw_dir / str(details["file"])).read_text(encoding="utf-8"))
    series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
    adjusted = pd.Series(
        np.asarray(series.close) * np.asarray(series.forward_factor),
        index=pd.to_datetime(series.dates),
    )
    return adjusted.pct_change(fill_method=None)


def _delisted_returns(tushare_dir: Path) -> dict[str, pd.Series]:
    daily = pd.read_parquet(
        tushare_dir / "delisted_daily.parquet", columns=["ts_code", "trade_date", "close"]
    )
    factor = pd.read_parquet(
        tushare_dir / "delisted_adj_factor.parquet",
        columns=["ts_code", "trade_date", "adj_factor"],
    )
    merged = daily.merge(factor, on=["ts_code", "trade_date"], how="inner", validate="one_to_one")
    result: dict[str, pd.Series] = {}
    for symbol, group in merged.groupby("ts_code", sort=True):
        dates = pd.to_datetime(group["trade_date"].astype(str))
        adjusted = pd.Series(
            group["close"].to_numpy() * group["adj_factor"].to_numpy(), index=dates
        ).sort_index()
        result[str(symbol)] = adjusted.pct_change(fill_method=None)
    return result


def _market_return(
    raw_dir: Path,
    selected: dict[str, dict[str, object]],
    delisted: dict[str, pd.Series],
    cache: Path,
) -> pd.Series:
    if cache.exists():
        frame = pd.read_parquet(cache)
        return frame.set_index("date")["market_return"].sort_index()
    sums: defaultdict[pd.Timestamp, float] = defaultdict(float)
    counts: defaultdict[pd.Timestamp, int] = defaultdict(int)
    sources = ((symbol, _raw_return(raw_dir, symbol, details)) for symbol, details in selected.items())
    for number, (_, returns) in enumerate(sources, start=1):
        for date, value in returns.dropna().items():
            sums[date] += float(value)
            counts[date] += 1
        if number % 500 == 0:
            print(json.dumps({"event": "market_pass", "symbols": number}), flush=True)
    for returns in delisted.values():
        for date, value in returns.dropna().items():
            sums[date] += float(value)
            counts[date] += 1
    dates = sorted(sums)
    market = pd.Series([sums[date] / counts[date] for date in dates], index=dates, name="market_return")
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(cache.suffix + ".tmp")
    market.rename_axis("date").reset_index().to_parquet(temporary, index=False)
    temporary.replace(cache)
    return market


def _beta_panel(
    raw_dir: Path,
    selected: dict[str, dict[str, object]],
    delisted: dict[str, pd.Series],
    market: pd.Series,
    signal_dates: list[pd.Timestamp],
    cache: Path,
) -> pd.DataFrame:
    if cache.exists():
        frame = pd.read_parquet(cache)
        frame["signal_date"] = pd.to_datetime(frame["signal_date"])
        if "residual_volatility" in frame:
            return frame
    rows = []
    for number, (symbol, details) in enumerate(sorted(selected.items()), start=1):
        styles = rolling_beta_and_residual_volatility(
            _raw_return(raw_dir, symbol, details), market
        ).reindex(signal_dates)
        rows.append(
            pd.DataFrame(
                {
                    "ts_code": symbol, "signal_date": signal_dates,
                    "beta": styles["beta"].to_numpy(),
                    "residual_volatility": styles["residual_volatility"].to_numpy(),
                }
            )
        )
        if number % 500 == 0:
            print(json.dumps({"event": "beta_pass", "symbols": number}), flush=True)
    for symbol, returns in sorted(delisted.items()):
        styles = rolling_beta_and_residual_volatility(returns, market).reindex(signal_dates)
        rows.append(
            pd.DataFrame(
                {
                    "ts_code": symbol, "signal_date": signal_dates,
                    "beta": styles["beta"].to_numpy(),
                    "residual_volatility": styles["residual_volatility"].to_numpy(),
                }
            )
        )
    frame = pd.concat(rows, ignore_index=True)
    temporary = cache.with_suffix(cache.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(cache)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--valuation-panel", type=Path, required=True)
    parser.add_argument("--supplemental-panel", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--market-cache", type=Path, required=True)
    parser.add_argument("--beta-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    base = pd.read_parquet(args.base_panel)
    base["signal_date"] = pd.to_datetime(base["signal_date"])
    keys = ["ts_code", "signal_date"]
    valuation_columns = ["earnings_yield", "book_to_price", "sales_to_price", "dividend_yield"]
    valuation = pd.read_parquet(args.valuation_panel, columns=[*keys, *valuation_columns])
    supplemental_columns = ["conservative_asset_growth", "conservative_equity_growth"]
    supplemental = pd.read_parquet(args.supplemental_panel, columns=[*keys, *supplemental_columns])
    frame = base.merge(valuation, on=keys, how="left", validate="one_to_one")
    frame = frame.merge(supplemental, on=keys, how="left", validate="one_to_one")

    daily = pd.read_parquet(
        args.tushare_dir / "daily_basic_month_end.parquet",
        columns=["ts_code", "trade_date", "circ_mv", "turnover_rate_f"],
    )
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    frame = frame.merge(daily, on=keys, how="left", validate="one_to_one")
    frame["size"] = np.log(frame["circ_mv"].where(frame["circ_mv"] > 0))
    frame["liquidity"] = np.log1p(frame["turnover_rate_f"].where(frame["turnover_rate_f"] >= 0))

    dates = sorted(pd.Timestamp(value) for value in frame["signal_date"].unique())
    members = pd.read_parquet(args.tushare_dir / "index_members_sw2021.parquet")
    frame = frame.merge(industry_panel(members, dates), on=keys, how="left", validate="many_to_one")
    frame["financial_sector"] = np.select(
        [frame["l1_code"].eq("801780.SI"), frame["l1_code"].eq("801790.SI")],
        ["bank", "nonbank_financial"],
        default="nonfinancial",
    )

    audit = json.loads(args.tdx_audit.read_text(encoding="utf-8"))
    selected = audit["selected"]
    delisted = _delisted_returns(args.tushare_dir)
    market = _market_return(args.tdx_raw, selected, delisted, args.market_cache)
    betas = _beta_panel(args.tdx_raw, selected, delisted, market, dates, args.beta_cache)
    frame = frame.merge(betas, on=keys, how="left", validate="one_to_one")

    frame = add_cross_sectional_styles(frame)
    frame["short_reversal"] = frame["reversal_1m"]
    frame["momentum"] = frame["momentum_12_1"]
    frame["quality_composite"] = np.nan
    frame["leverage"] = np.nan

    style_columns = [
        "l1_code", "financial_sector", "size", "nonlinear_size", "beta", "momentum",
        "short_reversal", "liquidity", "residual_volatility", "value_ep_z",
        "value_bp_z", "value_sp_z", "value_dy_z", "value_composite", "loss_dummy",
        "investment", "quality_composite", "leverage",
    ]
    output = frame[[*keys, *style_columns]].sort_values(keys)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    coverage = {column: float(output[column].notna().mean()) for column in style_columns if column not in {"l1_code", "financial_sector"}}
    payload = {
        "version": 4,
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(keys).sum()),
        "signal_months": int(output["signal_date"].nunique()),
        "coverage": coverage,
        "complete_controls": ["size", "nonlinear_size", "beta", "momentum", "short_reversal", "liquidity", "residual_volatility"],
        "proxy_controls": ["value_composite", "investment"],
        "blocked_controls": {"quality_composite": "DATA_BLOCKED_PARTIAL_QUARTERLY_PIT", "leverage": "DATA_BLOCKED_PARTIAL_QUARTERLY_PIT"},
        "market_beta": "252-trading-day rolling beta, minimum 120 observations, against local all-A equal-weight adjusted daily return",
        "value_protocol": "industry-standardized E/P, B/P, S/P and dividend yield; E/P ranks profitable firms only; loss_dummy is separate",
        "investment_protocol": "industry-standardized equal weight of conservative annual asset and equity growth; annual PIT proxy, not complete quarterly Investment",
        "entry_label": "T signal, T+1 adjusted open entry; style file does not alter frozen labels",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
