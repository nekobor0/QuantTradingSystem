"""Audit Phase 1 Tushare Parquet supplements and point-in-time coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def key_duplicates(frame: pd.DataFrame, columns: list[str]) -> int:
    return int(frame.duplicated(columns, keep=False).sum())


def nonempty_dates(values: pd.Series) -> pd.Series:
    result = values.fillna("").astype(str)
    return result[result != ""]


def active_listed(stock_basic: pd.DataFrame, trade_date: str) -> set[str]:
    list_date = stock_basic["list_date"].fillna("").astype(str)
    delist_date = stock_basic["delist_date"].fillna("").astype(str)
    active = (list_date <= trade_date) & ((delist_date == "") | (delist_date > trade_date))
    return set(stock_basic.loc[active, "ts_code"].astype(str))


def active_industries(members: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    in_date = members["in_date"].fillna("").astype(str)
    out_date = members["out_date"].fillna("").astype(str)
    active = (in_date != "") & (in_date <= trade_date) & ((out_date == "") | (out_date > trade_date))
    return members.loc[active, ["ts_code", "l1_code"]].drop_duplicates()


def audit(input_dir: Path) -> dict[str, Any]:
    stock = pd.read_parquet(input_dir / "stock_basic.parquet")
    calendar = pd.read_parquet(input_dir / "trade_cal.parquet")
    daily = pd.read_parquet(input_dir / "daily_basic_month_end.parquet")
    classify = pd.read_parquet(input_dir / "index_classify.parquet")
    members = pd.read_parquet(input_dir / "index_members_sw2021.parquet")
    st = pd.read_parquet(input_dir / "stock_st_month_end.parquet")
    weights = {
        "000300.SH": pd.read_parquet(input_dir / "index_weight_000300_SH.parquet"),
        "000905.SH": pd.read_parquet(input_dir / "index_weight_000905_SH.parquet"),
    }

    dates = sorted(daily["trade_date"].astype(str).unique())
    monthly_quality: list[dict[str, Any]] = []
    for trade_date in dates:
        expected = active_listed(stock, trade_date)
        observed = set(daily.loc[daily["trade_date"].astype(str) == trade_date, "ts_code"].astype(str))
        active_members = active_industries(members, trade_date)
        industry_counts = active_members.groupby("ts_code")["l1_code"].nunique()
        covered_industry = set(industry_counts.index) & expected
        monthly_quality.append(
            {
                "trade_date": trade_date,
                "eligible_listed": len(expected),
                "daily_basic_symbols": len(observed),
                "daily_basic_coverage": len(observed & expected) / len(expected) if expected else None,
                "industry_coverage": len(covered_industry) / len(expected) if expected else None,
                "industry_ambiguous_symbols": int((industry_counts > 1).sum()),
            }
        )
    monthly = pd.DataFrame(monthly_quality)

    daily_nulls = {
        column: int(daily[column].isna().sum())
        for column in ("total_mv", "circ_mv", "turnover_rate", "turnover_rate_f", "float_share")
    }
    weight_quality: dict[str, Any] = {}
    for code, frame in weights.items():
        counts = frame.groupby("trade_date")["con_code"].nunique()
        expected_count = 300 if code == "000300.SH" else 500
        weight_sums = frame.groupby("trade_date")["weight"].sum()
        weight_quality[code] = {
            "rows": len(frame),
            "months": int(counts.size),
            "first_date": str(counts.index.min()),
            "last_date": str(counts.index.max()),
            "constituent_count_min": int(counts.min()),
            "constituent_count_max": int(counts.max()),
            "months_not_expected_count": int((counts != expected_count).sum()),
            "weight_sum_min": float(weight_sums.min()),
            "weight_sum_max": float(weight_sums.max()),
            "duplicate_keys": key_duplicates(frame, ["index_code", "con_code", "trade_date"]),
        }

    report: dict[str, Any] = {
        "version": 1,
        "stock_basic": {
            "rows": len(stock),
            "listed": int((stock["list_status"] == "L").sum()),
            "delisted": int((stock["list_status"] == "D").sum()),
            "pending": int((stock["list_status"] == "P").sum()),
            "duplicate_ts_code": key_duplicates(stock, ["ts_code"]),
        },
        "trade_calendar": {
            "rows": len(calendar),
            "open_days": int((calendar["is_open"].astype(str) == "1").sum()),
            "duplicate_cal_date": key_duplicates(calendar, ["cal_date"]),
        },
        "daily_basic": {
            "rows": len(daily),
            "months": len(dates),
            "first_date": dates[0],
            "last_date": dates[-1],
            "duplicate_keys": key_duplicates(daily, ["ts_code", "trade_date"]),
            "null_counts": daily_nulls,
            "monthly_coverage_min": float(monthly["daily_basic_coverage"].min()),
            "monthly_coverage_median": float(monthly["daily_basic_coverage"].median()),
        },
        "industry": {
            "level_one_classifications": len(classify),
            "membership_rows": len(members),
            "duplicate_rows": int(members.duplicated().sum()),
            "monthly_coverage_min": float(monthly["industry_coverage"].min()),
            "monthly_coverage_median": float(monthly["industry_coverage"].median()),
            "monthly_ambiguous_symbols_max": int(monthly["industry_ambiguous_symbols"].max()),
        },
        "stock_st": {
            "rows": len(st),
            "months_with_rows": int(st["trade_date"].nunique()),
            "first_date": str(st["trade_date"].min()),
            "last_date": str(st["trade_date"].max()),
            "duplicate_keys": key_duplicates(st, ["ts_code", "trade_date"]),
        },
        "index_weights": weight_quality,
        "monthly_quality": monthly_quality,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "monthly_quality"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
