"""Build PIT cash-flow confirmation change factors from local financial files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


FACTORS = {
    "cash_profit_confirmation_yoy": "A股财报集中披露且散户更关注利润表；经营现金流/净利润同比改善代表盈利得到更强现金确认，公告后下一月收益更高。",
    "cash_revenue_confirmation_yoy": "A股投资者容易追逐收入增速；经营现金流/营业收入同比改善代表增长质量提高，公告后下一月收益更高。",
    "cash_profit_confirmation_acceleration": "A股对会计盈利质量恶化常反应滞后；现金流确认利润的同比改善继续加速时，公告后下一月收益更高。",
}


def load_cash_flow(directory: Path) -> pd.DataFrame:
    required = {"symbol", "announcement_date", "date", "CFOToNP", "CFOToOR"}
    frames = []
    for path in sorted(directory.glob("*_cash_flow.parquet")):
        frame = pd.read_parquet(path)
        if required.issubset(frame.columns):
            frames.append(frame[list(required)])
    if not frames:
        raise FileNotFoundError("no compatible cash-flow ratio files found")
    frame = pd.concat(frames, ignore_index=True)
    frame["announcement_date"] = pd.to_datetime(frame["announcement_date"], errors="coerce")
    frame["report_date"] = pd.to_datetime(frame.pop("date"), errors="coerce")
    frame = frame.dropna(subset=["symbol", "announcement_date", "report_date"])
    frame = frame.sort_values(["symbol", "report_date", "announcement_date"]).drop_duplicates(
        ["symbol", "report_date"], keep="last"
    )
    grouped = frame.groupby("symbol", sort=False)
    frame["cash_profit_confirmation_yoy"] = frame["CFOToNP"] - grouped["CFOToNP"].shift(4)
    frame["cash_revenue_confirmation_yoy"] = frame["CFOToOR"] - grouped["CFOToOR"].shift(4)
    frame["cash_profit_confirmation_acceleration"] = (
        frame["cash_profit_confirmation_yoy"]
        - frame.groupby("symbol", sort=False)["cash_profit_confirmation_yoy"].shift(4)
    )
    return frame[["symbol", "announcement_date", *FACTORS]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--financial-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    panel = pd.read_parquet(args.base_panel)
    base_columns = list(panel.columns)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    events = load_cash_flow(args.financial_dir).rename(columns={"symbol": "ts_code"})
    panel = pd.merge_asof(
        panel.sort_values(["signal_date", "ts_code"]),
        events.sort_values(["announcement_date", "ts_code"]),
        left_on="signal_date",
        right_on="announcement_date",
        by="ts_code",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="announcement_date")
    panel = panel[base_columns + list(FACTORS)].sort_values(["ts_code", "signal_date"])
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    panel.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    metadata = {
        "version": 1,
        "factor_hypotheses": FACTORS,
        "rows": len(panel),
        "coverage_before_universe_filters": {name: float(panel[name].notna().mean()) for name in FACTORS},
        "protocol": "quarterly ratios; latest filing per report period; four-quarter seasonal difference; available only on/after announcement_date",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
