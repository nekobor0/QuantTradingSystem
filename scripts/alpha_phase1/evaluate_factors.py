"""Apply the frozen Phase 1 single-factor gates and emit auditable results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

def industry_panel(members: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    output = []
    members = members.copy()
    members["in_date"] = members["in_date"].fillna("").astype(str)
    members["out_date"] = members["out_date"].fillna("").astype(str)
    for date in dates:
        text = date.strftime("%Y%m%d")
        active = members[(members.in_date <= text) & ((members.out_date == "") | (members.out_date > text))]
        active = active.sort_values(["ts_code", "in_date", "l1_code"]).drop_duplicates("ts_code", keep="last")
        output.append(active[["ts_code", "l1_code"]].assign(signal_date=date))
    return pd.concat(output, ignore_index=True)


def neutral_residual(group: pd.DataFrame, factor: str) -> pd.Series:
    valid = group[[factor, "log_mv", "volatility_60", "l1_code"]].dropna()
    result = pd.Series(np.nan, index=group.index)
    if len(valid) < 100:
        return result
    low, high = valid[factor].quantile([0.01, 0.99])
    y = valid[factor].clip(low, high).rank(pct=True).to_numpy()
    industry = pd.get_dummies(valid["l1_code"], drop_first=True, dtype=float)
    x = np.column_stack([np.ones(len(valid)), valid["log_mv"], valid["volatility_60"], industry])
    result.loc[valid.index] = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
    return result


def monthly_ics(frame: pd.DataFrame, factor: str, label: str, domain: str | None = None) -> pd.Series:
    data = frame if domain is None else frame[frame[domain]]
    return data.groupby("signal_date").apply(
        lambda g: spearmanr(g[factor], g[label], nan_policy="omit").statistic if g[[factor, label]].dropna().shape[0] >= 30 else np.nan,
        include_groups=False,
    ).dropna()


def metrics(ics: pd.Series) -> dict[str, float | int | None]:
    mean = float(ics.mean()) if len(ics) else None
    std = float(ics.std(ddof=1)) if len(ics) > 1 else None
    return {
        "months": len(ics), "mean": mean, "std": std,
        "ic_ir": mean / std if mean is not None and std else None,
        "positive_ratio": float((ics > 0).mean()) if len(ics) else None,
    }


def monotonicity(frame: pd.DataFrame, factor: str) -> dict[str, object]:
    rows = []
    for _, group in frame[["signal_date", factor, "forward_return"]].dropna().groupby("signal_date"):
        if len(group) < 100:
            continue
        ranked = group[factor].rank(method="first")
        decile = pd.qcut(ranked, 10, labels=False)
        rows.append(group.assign(decile=decile).groupby("decile")["forward_return"].mean())
    average = pd.concat(rows, axis=1).mean(axis=1) if rows else pd.Series(dtype=float)
    differences = average.diff().dropna()
    return {
        "decile_returns": [float(value) for value in average],
        "increasing_adjacent_pairs": int((differences > 0).sum()),
        "long_short": float(average.iloc[-1] - average.iloc[0]) if len(average) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pure-panel", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    if args.metadata:
        factor_hypotheses = json.loads(args.metadata.read_text(encoding="utf-8"))["factor_hypotheses"]
    else:
        from build_factor_panel import FACTORS

        factor_hypotheses = FACTORS
    frame = pd.read_parquet(args.panel)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    daily = pd.read_parquet(args.tushare_dir / "daily_basic_month_end.parquet")
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    frame = frame.merge(daily[["ts_code", "signal_date", "total_mv"]], on=["ts_code", "signal_date"], how="left")
    frame["log_mv"] = np.log(frame["total_mv"].where(frame["total_mv"] > 0))
    members = pd.read_parquet(args.tushare_dir / "index_members_sw2021.parquet")
    frame = frame.merge(industry_panel(members, sorted(frame.signal_date.unique())), on=["ts_code", "signal_date"], how="left")
    st = pd.read_parquet(args.tushare_dir / "stock_st_month_end.parquet")
    st["signal_date"] = pd.to_datetime(st.pop("trade_date").astype(str))
    frame = frame.merge(st[["ts_code", "signal_date"]].drop_duplicates().assign(is_st=True), on=["ts_code", "signal_date"], how="left")
    frame["is_st"] = frame["is_st"].fillna(False)
    for code, column in (("000300_SH", "in_hs300"), ("000905_SH", "in_zz500")):
        weights = pd.read_parquet(args.tushare_dir / f"index_weight_{code}.parquet")
        weights["signal_date"] = pd.to_datetime(weights.pop("trade_date").astype(str))
        frame = frame.merge(weights[["con_code", "signal_date"]].rename(columns={"con_code": "ts_code"}).drop_duplicates().assign(**{column: True}), on=["ts_code", "signal_date"], how="left")
        frame[column] = frame[column].fillna(False)
    frame = frame[~frame.is_st & frame.total_mv.notna() & frame.l1_code.notna()].copy()

    results = {}
    for factor in factor_hypotheses:
        pure = f"pure_{factor}"
        frame[pure] = frame.groupby("signal_date", group_keys=False).apply(lambda g: neutral_residual(g, factor), include_groups=False)
        raw_ic = monthly_ics(frame, factor, "forward_return")
        pure_ic = monthly_ics(frame, pure, "forward_return")
        delay_ic = monthly_ics(frame, pure, "forward_return_delay2")
        oos = monthly_ics(frame[frame.signal_date >= "2023-07-01"], pure, "forward_return")
        hs300 = monthly_ics(frame, pure, "forward_return", "in_hs300")
        zz500 = monthly_ics(frame, pure, "forward_return", "in_zz500")
        coverage = float(frame[factor].notna().mean())
        raw_mean, pure_mean = abs(raw_ic.mean()), abs(pure_ic.mean())
        mono = monotonicity(frame, pure)
        gate = (
            coverage >= 0.95 and abs(pure_ic.mean()) > 0.04 and metrics(pure_ic)["ic_ir"] > 0.6
            and metrics(pure_ic)["positive_ratio"] > 0.6 and mono["increasing_adjacent_pairs"] >= 8
            and (pure_mean / raw_mean if raw_mean else 0) >= 0.7
            and all(series.mean() > 0 for series in (delay_ic, oos, hs300, zz500))
        )
        results[factor] = {
            "hypothesis": factor_hypotheses[factor], "coverage": coverage, "raw": metrics(raw_ic),
            "pure": metrics(pure_ic), "delay2": metrics(delay_ic), "oos_3y": metrics(oos),
            "hs300": metrics(hs300), "zz500": metrics(zz500), "neutral_ic_retention": pure_mean / raw_mean if raw_mean else None,
            "monotonicity": mono, "passes_all_gates": bool(gate),
        }
        print(json.dumps({"factor": factor, "pure_ic": pure_ic.mean(), "pass": bool(gate)}), flush=True)
    pure_columns = [f"pure_{factor}" for factor in factor_hypotheses]
    correlations = frame[pure_columns].corr(method="spearman")
    passing = [name for name, value in results.items() if value["passes_all_gates"]]
    payload = {"version": 1, "rows_after_filters": len(frame), "factors_tested": len(factor_hypotheses), "passing_factors": passing, "results": results, "pure_factor_correlation": correlations.to_dict()}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    frame[["ts_code", "signal_date", "forward_return", "forward_return_delay2", *pure_columns]].to_parquet(args.pure_panel, index=False)
    print(json.dumps({"passing_factors": passing}, ensure_ascii=False))


if __name__ == "__main__":
    main()
