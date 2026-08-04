"""Build theory-frozen share-supply and point-in-time financial factors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


FACTORS = {
    "equity_supply_3m": "公司总股本在三个月内扩张会增加股票供给并稀释原股东，随后一个月的截面收益更低。",
    "free_float_supply_3m": "自由流通股本在三个月内增加会形成可交易供给冲击，随后一个月的截面收益更低。",
    "free_float_supply_12m": "过去一年持续增加的自由流通供给会造成更持久的供给压力，随后一个月的截面收益更低。",
    "turnover_attention_reversal": "自由流通口径换手率相对自身过去一年中位数异常升高代表短期过度关注，随后一个月发生反转。",
    "gross_profitability": "较高毛利率反映难以复制的产品议价能力，公告后下一月的截面收益更高。",
    "gross_margin_improvement": "年度毛利率同比改善代表经营质量在增强，公告后下一月的截面收益更高。",
    "roe_improvement": "年度净资产收益率同比改善代表资本效率提高，公告后下一月的截面收益更高。",
    "conservative_asset_growth": "资产扩张越激进越可能包含低回报投资，因此年度资产增长越低，公告后下一月收益越高。",
    "conservative_equity_growth": "净资产扩张越快越可能伴随融资稀释，因此年度净资产增长越低，公告后下一月收益越高。",
    "fundamental_profit_growth": "年度净利润增长更强代表基本面信息尚未被完全吸收，公告后下一月收益更高。",
}


def _load_kind(directory: Path, kind: str, columns: list[str]) -> pd.DataFrame:
    files = sorted(directory.glob(f"*_{kind}.parquet"))
    if not files:
        raise FileNotFoundError(f"No *_{kind}.parquet files under {directory}")
    frames = []
    for path in files:
        frame = pd.read_parquet(path)
        frames.append(frame[[column for column in columns if column in frame.columns]])
    return pd.concat(frames, ignore_index=True)


def _annual_events(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["report_date"] = pd.to_datetime(frame.pop("date"), errors="coerce")
    frame["announcement_date"] = pd.to_datetime(frame["announcement_date"], errors="coerce")
    frame = frame[
        frame["symbol"].notna()
        & frame["announcement_date"].notna()
        & frame["report_date"].notna()
        & (frame["report_date"].dt.month == 12)
    ]
    return frame.sort_values(["symbol", "report_date", "announcement_date"]).drop_duplicates(
        ["symbol", "report_date"], keep="last"
    )


def _asof_merge(panel: pd.DataFrame, events: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    right = events[["symbol", "announcement_date", *columns]].rename(columns={"symbol": "ts_code"})
    left = panel.sort_values(["signal_date", "ts_code"])
    right = right.sort_values(["announcement_date", "ts_code"])
    return pd.merge_asof(
        left,
        right,
        left_on="signal_date",
        right_on="announcement_date",
        by="ts_code",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="announcement_date")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--daily-basic", type=Path, required=True)
    parser.add_argument("--financial-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    panel = pd.read_parquet(args.base_panel)
    base_columns = list(panel.columns)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    daily = pd.read_parquet(args.daily_basic)
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    daily = daily.sort_values(["ts_code", "signal_date"])
    grouped = daily.groupby("ts_code", sort=False)
    for months, name, source in (
        (3, "equity_supply_3m", "total_share"),
        (3, "free_float_supply_3m", "free_share"),
        (12, "free_float_supply_12m", "free_share"),
    ):
        prior = grouped[source].shift(months)
        daily[name] = -np.log(daily[source].where(daily[source] > 0) / prior.where(prior > 0))
    baseline = grouped["turnover_rate_f"].transform(lambda values: values.shift(1).rolling(12, min_periods=6).median())
    daily["turnover_attention_reversal"] = -np.log(
        daily["turnover_rate_f"].where(daily["turnover_rate_f"] > 0) / baseline.where(baseline > 0)
    )
    share_factors = [name for name in FACTORS if name in daily.columns]
    panel = panel.merge(
        daily[["ts_code", "signal_date", *share_factors]],
        on=["ts_code", "signal_date"],
        how="left",
    )

    profit = _annual_events(
        _load_kind(
            args.financial_dir,
            "profit",
            ["symbol", "announcement_date", "date", "roe", "gross_margin"],
        )
    )
    profit["gross_profitability"] = profit["gross_margin"]
    profit["gross_margin_improvement"] = profit.groupby("symbol")["gross_margin"].diff()
    profit["roe_improvement"] = profit.groupby("symbol")["roe"].diff()
    panel = _asof_merge(
        panel,
        profit,
        ["gross_profitability", "gross_margin_improvement", "roe_improvement"],
    )

    growth = _annual_events(
        _load_kind(
            args.financial_dir,
            "growth",
            [
                "symbol", "announcement_date", "date", "asset_growth",
                "equity_growth", "net_profit_growth",
            ],
        )
    )
    growth["conservative_asset_growth"] = -growth["asset_growth"]
    growth["conservative_equity_growth"] = -growth["equity_growth"]
    growth["fundamental_profit_growth"] = growth["net_profit_growth"]
    panel = _asof_merge(
        panel,
        growth,
        ["conservative_asset_growth", "conservative_equity_growth", "fundamental_profit_growth"],
    )

    output_columns = base_columns + list(FACTORS)
    panel = panel[output_columns].sort_values(["ts_code", "signal_date"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(args.output, index=False)
    coverage = {factor: float(panel[factor].notna().mean()) for factor in FACTORS}
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "coverage_before_universe_filters": coverage,
        "financial_protocol": "annual reports only; value becomes available on announcement_date and is carried forward",
        "sources": {
            "share_supply": str(args.daily_basic),
            "financials": str(args.financial_dir),
        },
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
