"""Auditable Phase-1 single-factor evaluation for an A-share long-only strategy."""

from __future__ import annotations

from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd


CONTROL_COLUMNS = ["log_circ_mv", "volatility_60", "log_turnover", "momentum_12_1"]


def industry_panel(members: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    members = members.copy()
    members["in_date"] = members["in_date"].fillna("").astype(str)
    members["out_date"] = members["out_date"].fillna("").astype(str)
    rows = []
    for date in dates:
        text = date.strftime("%Y%m%d")
        active = members[
            (members["in_date"] <= text)
            & ((members["out_date"] == "") | (members["out_date"] > text))
        ]
        active = active.sort_values(["ts_code", "in_date", "l1_code"]).drop_duplicates(
            "ts_code", keep="last"
        )
        rows.append(active[["ts_code", "l1_code"]].assign(signal_date=date))
    return pd.concat(rows, ignore_index=True)


def prepare_universe(base_panel: pd.DataFrame, tushare_dir: Path) -> pd.DataFrame:
    frame = base_panel.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])

    daily = pd.read_parquet(
        tushare_dir / "daily_basic_month_end.parquet",
        columns=["ts_code", "trade_date", "circ_mv", "total_mv", "turnover_rate_f"],
    )
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date").astype(str))
    frame = frame.merge(daily, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame["log_circ_mv"] = np.log(frame["circ_mv"].where(frame["circ_mv"] > 0))
    frame["log_turnover"] = np.log1p(frame["turnover_rate_f"].where(frame["turnover_rate_f"] >= 0))

    members = pd.read_parquet(tushare_dir / "index_members_sw2021.parquet")
    dates = sorted(pd.Timestamp(value) for value in frame["signal_date"].unique())
    frame = frame.merge(
        industry_panel(members, dates), on=["ts_code", "signal_date"], how="left", validate="many_to_one"
    )

    stocks = pd.read_parquet(
        tushare_dir / "stock_basic.parquet",
        columns=["ts_code", "name", "market", "list_date", "delist_date"],
    ).drop_duplicates("ts_code", keep="last")
    stocks["list_date"] = pd.to_datetime(stocks["list_date"], errors="coerce")
    stocks["delist_date"] = pd.to_datetime(stocks["delist_date"], errors="coerce")
    frame = frame.merge(stocks, on="ts_code", how="left", validate="many_to_one")
    frame["pit_active"] = (frame["list_date"] <= frame["signal_date"]) & (
        frame["delist_date"].isna() | (frame["signal_date"] < frame["delist_date"])
    )
    frame["is_main_board"] = frame["market"].eq("主板")

    st = pd.read_parquet(tushare_dir / "stock_st_month_end.parquet", columns=["ts_code", "trade_date"])
    st["signal_date"] = pd.to_datetime(st.pop("trade_date").astype(str))
    st = st.drop_duplicates(["ts_code", "signal_date"]).assign(is_st=True)
    frame = frame.merge(st, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame["is_st"] = frame["is_st"].fillna(False).astype(bool)

    for code, column in (
        ("000300_SH", "in_hs300"),
        ("000905_SH", "in_zz500"),
        ("000852_SH", "in_zz1000"),
    ):
        weights = pd.read_parquet(
            tushare_dir / f"index_weight_{code}.parquet", columns=["con_code", "trade_date"]
        )
        weights["signal_date"] = pd.to_datetime(weights.pop("trade_date").astype(str))
        weights = (
            weights.rename(columns={"con_code": "ts_code"})
            .drop_duplicates(["ts_code", "signal_date"])
            .assign(**{column: True})
        )
        frame = frame.merge(weights, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
        frame[column] = frame[column].fillna(False).astype(bool)
    frame["in_mid_small"] = frame["in_zz500"] | frame["in_zz1000"]

    frame["eligible_quality"] = (
        frame["pit_active"]
        & frame["circ_mv"].gt(0)
        & frame["forward_return"].notna()
        & frame["entry_1_tradable"].astype(bool)
        & frame["exit_1_tradable"].astype(bool)
    )
    frame["eligible_evaluation"] = frame["eligible_quality"] & frame[
        [*CONTROL_COLUMNS, "l1_code"]
    ].notna().all(axis=1)
    return frame


def _zscore(values: pd.Series) -> pd.Series:
    low, high = values.quantile([0.01, 0.99])
    clipped = values.clip(low, high)
    std = clipped.std(ddof=0)
    return (clipped - clipped.mean()) / std if std and np.isfinite(std) else clipped * 0.0


def neutralize(frame: pd.DataFrame, factor: str) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, group in frame.groupby("signal_date", sort=False):
        valid = group["eligible_evaluation"] & group[factor].notna()
        sample = group.loc[valid, [*CONTROL_COLUMNS, "l1_code"]]
        if len(sample) < 100:
            continue
        raw_y = group.loc[valid, factor]
        y = raw_y.clip(*raw_y.quantile([0.01, 0.99])).rank(pct=True)
        numeric = np.column_stack([_zscore(sample[column]).to_numpy() for column in CONTROL_COLUMNS])
        industries = pd.get_dummies(sample["l1_code"], drop_first=True, dtype=float).to_numpy()
        x = np.column_stack([np.ones(len(sample)), numeric, industries])
        residual = y.to_numpy() - x @ np.linalg.lstsq(x, y.to_numpy(), rcond=None)[0]
        result.loc[sample.index] = residual
    return result


def series_summary(values: pd.Series) -> dict[str, float | int | None]:
    values = values.dropna().astype(float)
    mean = float(values.mean()) if len(values) else None
    std = float(values.std(ddof=1)) if len(values) > 1 else None
    return {
        "months": int(len(values)),
        "mean": mean,
        "std": std,
        "t_stat": mean / (std / sqrt(len(values))) if mean is not None and std else None,
        "ir": mean / std if mean is not None and std else None,
        "positive_ratio": float((values > 0).mean()) if len(values) else None,
    }


def monthly_ic(frame: pd.DataFrame, factor: str, mask: pd.Series | None = None) -> pd.Series:
    selected = frame["eligible_evaluation"] if mask is None else frame["eligible_evaluation"] & mask
    data = frame.loc[selected, ["signal_date", factor, "forward_return"]].dropna()
    return data.groupby("signal_date").apply(
        lambda group: group[factor].corr(group["forward_return"], method="spearman")
        if len(group) >= 30
        else np.nan,
        include_groups=False,
    ).dropna()


def decile_analysis(
    frame: pd.DataFrame,
    factor: str,
    mask: pd.Series | None = None,
) -> tuple[dict[str, object], dict[pd.Timestamp, dict[str, float]]]:
    selected = frame["eligible_evaluation"] if mask is None else frame["eligible_evaluation"] & mask
    excess_rows: list[pd.Series] = []
    d1_values: dict[pd.Timestamp, float] = {}
    holdings: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group in frame.loc[selected].groupby("signal_date", sort=True):
        benchmark = group["forward_return"].mean()
        candidates = group.dropna(subset=[factor, "forward_return"]).sort_values(
            [factor, "ts_code"], kind="stable"
        )
        if len(candidates) < 100:
            continue
        candidates = candidates.copy()
        candidates["decile"] = np.minimum(np.arange(len(candidates)) * 10 // len(candidates), 9)
        returns = candidates.groupby("decile")["forward_return"].mean().reindex(range(10))
        excess = returns - benchmark
        excess_rows.append(excess.rename(date))
        d1_values[pd.Timestamp(date)] = float(excess.loc[9])
        top = candidates.loc[candidates["decile"] == 9, "ts_code"].astype(str)
        holdings[pd.Timestamp(date)] = {symbol: 1.0 / len(top) for symbol in top}
    table = pd.DataFrame(excess_rows)
    average = table.mean(axis=0) if len(table) else pd.Series(index=range(10), dtype=float)
    differences = average.diff().dropna()
    summary: dict[str, object] = {
        "d1_excess": series_summary(pd.Series(d1_values, dtype=float)),
        "decile_excess": [float(average.get(number, np.nan)) for number in range(10)],
        "increasing_adjacent_pairs": int((differences > 0).sum()),
        "d1_minus_d10": float(average.get(9, np.nan) - average.get(0, np.nan)),
    }
    return summary, holdings


def turnover_summary(holdings: dict[pd.Timestamp, dict[str, float]]) -> dict[str, float | int | None]:
    dates = sorted(holdings)
    values = []
    for previous_date, current_date in zip(dates, dates[1:]):
        previous, current = holdings[previous_date], holdings[current_date]
        values.append(sum(max(weight - previous.get(symbol, 0.0), 0.0) for symbol, weight in current.items()))
    summary = series_summary(pd.Series(values, dtype=float))
    return {
        "transitions": int(len(values)),
        "monthly_one_way_mean": summary["mean"],
        "monthly_one_way_max": float(max(values)) if values else None,
        "annualized_one_way": float(summary["mean"] * 12) if summary["mean"] is not None else None,
        "high_frequency_flag": bool(summary["mean"] is not None and summary["mean"] > 1.5),
    }


def quality_summary(frame: pd.DataFrame, factor: str) -> dict[str, float | int | None]:
    eligible = frame.loc[frame["eligible_quality"]]
    available = eligible[factor].notna()
    total_cap = eligible["circ_mv"].sum()
    st_rows = eligible["is_st"].fillna(False).astype(bool) if "is_st" in eligible else None
    return {
        "eligible_rows": int(len(eligible)),
        "missing_rate": float(1.0 - available.mean()) if len(eligible) else None,
        "stock_coverage": float(available.mean()) if len(eligible) else None,
        "float_mv_coverage": float(eligible.loc[available, "circ_mv"].sum() / total_cap)
        if total_cap > 0
        else None,
        "st_row_share": float(st_rows.mean()) if st_rows is not None and len(eligible) else None,
        "st_float_mv_share": float(eligible.loc[st_rows, "circ_mv"].sum() / total_cap)
        if st_rows is not None and total_cap > 0
        else None,
    }


def a_share_environment(factor: str) -> str:
    if "holder" in factor:
        return "A股散户持有人占比较高且股东户数按公告离散披露，异常筹码集中可能被价格缓慢吸收。"
    if any(word in factor for word in ("institutional", "retail", "smart_money")):
        return "A股散户交易占比较高、T+1与涨跌停制度会延长订单流信息扩散和拥挤反转。"
    if any(word in factor for word in ("supply", "asset_growth", "equity_growth")):
        return "A股再融资、解禁和政策周期带来的供给变化突出，散户对稀释压力可能反应不足。"
    if any(word in factor for word in ("profit", "margin", "roe", "earnings", "book", "sales", "dividend")):
        return "A股财报集中披露且政策驱动风格轮动明显，基本面信息在散户主导定价中可能缓慢扩散。"
    if "momentum" in factor:
        return "A股政策主题轮动、涨跌停与机构分批调仓可能造成趋势信息的渐进扩散。"
    return "A股散户追涨杀跌、T+1和涨跌停约束会放大注意力交易，并使短期价格冲击随后修复。"


def evaluate_factor(frame: pd.DataFrame, factor: str, hypothesis: str) -> tuple[dict[str, object], pd.Series]:
    pure_name = f"pure_{factor}"
    pure = neutralize(frame, factor)
    frame[pure_name] = pure
    raw_ic = monthly_ic(frame, factor)
    pure_ic = monthly_ic(frame, pure_name)
    raw_deciles, _ = decile_analysis(frame, factor)
    pure_deciles, holdings = decile_analysis(frame, pure_name)
    last_period = frame["signal_date"].max().to_period("M")
    cutoff = (last_period - 35).to_timestamp()
    domains = {
        "oos_3y": frame["signal_date"] >= cutoff,
        "hs300": frame["in_hs300"],
        "csi500_csi1000": frame["in_mid_small"],
        "main_board": frame["is_main_board"],
    }
    domain_results = {
        name: decile_analysis(frame, pure_name, mask)[0]["d1_excess"] for name, mask in domains.items()
    }
    quality = quality_summary(frame, factor)
    raw_d1 = raw_deciles["d1_excess"]
    pure_d1 = pure_deciles["d1_excess"]
    raw_mean = raw_d1["mean"]
    pure_mean = pure_d1["mean"]
    decay = 1.0 - pure_mean / raw_mean if raw_mean is not None and raw_mean > 0 and pure_mean is not None else None
    gate_checks = {
        "missing_rate_lt_5pct": quality["missing_rate"] is not None and quality["missing_rate"] < 0.05,
        "float_mv_coverage_ge_80pct": quality["float_mv_coverage"] is not None and quality["float_mv_coverage"] >= 0.80,
        "pure_ic_abs_gt_004": len(pure_ic) > 0 and abs(pure_ic.mean()) > 0.04,
        "pure_ic_ir_gt_06": len(pure_ic) > 1 and pure_ic.std(ddof=1) > 0 and pure_ic.mean() / pure_ic.std(ddof=1) > 0.6,
        "pure_ic_positive_ratio_gt_60pct": len(pure_ic) > 0 and (pure_ic > 0).mean() > 0.60,
        "raw_d1_mean_gt_15pct": raw_mean is not None and raw_mean > 0.015,
        "raw_d1_t_gt_2": raw_d1["t_stat"] is not None and raw_d1["t_stat"] > 2.0,
        "pure_d1_positive": pure_mean is not None and pure_mean > 0,
        "pure_d1_t_gt_2": pure_d1["t_stat"] is not None and pure_d1["t_stat"] > 2.0,
        "pure_d1_decay_lt_40pct": decay is not None and decay < 0.40,
        "monotonic_pairs_ge_8": pure_deciles["increasing_adjacent_pairs"] >= 8,
        "d1_gt_d10": pure_deciles["d1_minus_d10"] > 0,
        **{
            f"{name}_pure_d1_positive": value["mean"] is not None and value["mean"] > 0
            for name, value in domain_results.items()
        },
    }
    result: dict[str, object] = {
        "hypothesis": hypothesis,
        "a_share_environment": a_share_environment(factor),
        "quality": quality,
        "raw_ic": series_summary(raw_ic),
        "pure_ic": series_summary(pure_ic),
        "raw_deciles": raw_deciles,
        "pure_deciles": pure_deciles,
        "pure_d1_decay": decay,
        "turnover": turnover_summary(holdings),
        "domains": domain_results,
        "gate_checks": {key: bool(value) for key, value in gate_checks.items()},
        "passes_all_gates": bool(all(gate_checks.values())),
    }
    return result, pure.astype("float32")
