"""PIT signal construction for F7 CSI1000 industry earnings diffusion."""

from __future__ import annotations

import numpy as np
import pandas as pd


FINANCIAL_VALUE_COLUMNS = ("q_sales_yoy", "dt_netprofit_yoy", "q_roe")


def _dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values.astype("string"), format="mixed", errors="coerce")


def financial_acceleration_pit(financial: pd.DataFrame, signal_dates: list[pd.Timestamp]) -> pd.DataFrame:
    required = {"ts_code", "ann_date", "end_date", "update_flag", *FINANCIAL_VALUE_COLUMNS}
    missing = required - set(financial.columns)
    if missing:
        raise ValueError(f"financial data missing columns: {sorted(missing)}")
    frame = financial.copy()
    frame["ann_date"] = _dates(frame["ann_date"])
    frame["end_date"] = _dates(frame["end_date"])
    frame["update_flag"] = pd.to_numeric(frame["update_flag"], errors="coerce").fillna(-1)
    frame = frame.dropna(subset=["ts_code", "ann_date", "end_date"])
    frame = frame[frame["end_date"].dt.strftime("%m%d").isin({"0331", "0630", "0930", "1231"})]
    outputs = []
    for signal_date in sorted(pd.Timestamp(value) for value in signal_dates):
        visible = frame.loc[frame["ann_date"].le(signal_date)].sort_values(
            ["ts_code", "end_date", "ann_date", "update_flag"], kind="stable"
        )
        visible = visible.drop_duplicates(["ts_code", "end_date"], keep="last")
        visible = visible.sort_values(["ts_code", "end_date"], kind="stable")
        visible["previous_end_date"] = visible.groupby("ts_code")["end_date"].shift(1)
        consecutive = visible["previous_end_date"].notna() & (
            visible["previous_end_date"] + pd.offsets.QuarterEnd()
        ).eq(visible["end_date"])
        for column in FINANCIAL_VALUE_COLUMNS:
            visible[f"previous_{column}"] = visible.groupby("ts_code")[column].shift(1).where(consecutive)
        latest = visible.groupby("ts_code", sort=False).tail(1).copy()
        latest["signal_date"] = signal_date
        latest["revenue_acceleration"] = latest["q_sales_yoy"] - latest["previous_q_sales_yoy"]
        latest["deducted_profit_acceleration"] = latest["dt_netprofit_yoy"] - latest["previous_dt_netprofit_yoy"]
        latest["roe_improvement"] = latest["q_roe"] - latest["previous_q_roe"]
        outputs.append(
            latest[
                [
                    "signal_date",
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "revenue_acceleration",
                    "deducted_profit_acceleration",
                    "roe_improvement",
                ]
            ]
        )
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def _consensus_for_target(reports: pd.DataFrame, as_of: pd.Timestamp, target: str, lookback_days: int) -> pd.DataFrame:
    lower = as_of - pd.Timedelta(days=lookback_days)
    visible = reports[
        reports["report_date"].between(lower, as_of)
        & reports["quarter"].eq(target)
        & reports["np"].gt(0)
    ].sort_values(["ts_code", "org_name", "report_date", "create_time"], kind="stable")
    latest = visible.drop_duplicates(["ts_code", "org_name"], keep="last")
    return latest.groupby("ts_code").agg(
        consensus_np=("np", "median"),
        latest_report_date=("report_date", "max"),
    )


def analyst_revision_pit(
    reports: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    *,
    lookback_days: int = 90,
) -> pd.DataFrame:
    required = {"ts_code", "report_date", "org_name", "quarter", "np", "create_time"}
    missing = required - set(reports.columns)
    if missing:
        raise ValueError(f"report data missing columns: {sorted(missing)}")
    frame = reports.copy()
    frame["report_date"] = _dates(frame["report_date"])
    frame["create_time"] = pd.to_datetime(frame["create_time"], errors="coerce")
    frame["quarter"] = frame["quarter"].astype("string")
    frame["np"] = pd.to_numeric(frame["np"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "report_date", "org_name", "quarter", "np"])
    outputs = []
    for signal_date in sorted(pd.Timestamp(value) for value in signal_dates):
        if signal_date.month == 1:
            continue
        target = f"{signal_date.year + 1}Q4"
        prior_date = signal_date + pd.offsets.MonthEnd(-1)
        current = _consensus_for_target(frame, signal_date, target, lookback_days)
        prior = _consensus_for_target(frame, prior_date, target, lookback_days)
        joined = current.join(prior.add_prefix("previous_"), how="inner").dropna(subset=["consensus_np", "previous_consensus_np"])
        joined = joined[(joined["consensus_np"] > 0) & (joined["previous_consensus_np"] > 0)]
        joined["earnings_revision"] = np.log(joined["consensus_np"] / joined["previous_consensus_np"])
        joined["signal_date"] = signal_date
        joined["previous_as_of_date"] = prior_date
        joined["target_quarter"] = target
        outputs.append(joined.reset_index())
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return float("nan")
    ordered = pd.DataFrame({"value": values[valid], "weight": weights[valid]}).sort_values("value")
    cutoff = ordered["weight"].sum() / 2.0
    return float(ordered.loc[ordered["weight"].cumsum().ge(cutoff), "value"].iloc[0])


def winsorize_company_values(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return numeric
    lower, upper = valid.quantile([0.01, 0.99])
    return numeric.clip(lower=lower, upper=upper)


def build_csi1000_member_panel(
    index_weights: pd.DataFrame,
    industry_members: pd.DataFrame,
    market_caps: pd.DataFrame,
) -> pd.DataFrame:
    weights = index_weights.rename(columns={"trade_date": "signal_date", "con_code": "ts_code"}).copy()
    weights["signal_date"] = _dates(weights["signal_date"])
    weights["benchmark_weight"] = pd.to_numeric(weights["weight"], errors="coerce") / 100.0
    industries = industry_members[["ts_code", "l1_code", "in_date", "out_date"]].copy()
    industries["in_date"] = _dates(industries["in_date"])
    industries["out_date"] = _dates(industries["out_date"])
    panel = weights.merge(industries, on="ts_code", how="left")
    panel = panel[
        panel["in_date"].le(panel["signal_date"])
        & (panel["out_date"].isna() | panel["out_date"].ge(panel["signal_date"]))
    ]
    overlapping = panel.groupby(["signal_date", "ts_code"])["l1_code"].nunique()
    if overlapping.gt(1).any():
        raise ValueError("conflicting overlapping PIT industry memberships")
    panel = panel.sort_values(
        ["signal_date", "ts_code", "l1_code", "in_date", "out_date"],
        kind="stable",
        na_position="last",
    ).drop_duplicates(["signal_date", "ts_code"], keep="first")
    caps = market_caps.rename(columns={"trade_date": "signal_date"})[
        ["signal_date", "ts_code", "total_mv"]
    ].copy()
    caps["signal_date"] = _dates(caps["signal_date"])
    caps["total_mv"] = pd.to_numeric(caps["total_mv"], errors="coerce") * 10_000.0
    panel = panel.merge(caps, on=["signal_date", "ts_code"], how="left", validate="one_to_one")
    return panel[["signal_date", "ts_code", "l1_code", "benchmark_weight", "total_mv"]].sort_values(
        ["signal_date", "ts_code"], kind="stable"
    ).reset_index(drop=True)


def stock_forward_return_3m(execution_labels: pd.DataFrame) -> pd.DataFrame:
    required = {"ts_code", "signal_date", "mark_return_1m"}
    missing = required - set(execution_labels.columns)
    if missing:
        raise ValueError(f"execution labels missing columns: {sorted(missing)}")
    columns = ["ts_code", "signal_date", "mark_return_1m"]
    if "entry_tradable" in execution_labels:
        columns.append("entry_tradable")
    source = execution_labels[columns].copy()
    source["signal_date"] = pd.to_datetime(source["signal_date"])
    source["period"] = source["signal_date"].dt.to_period("M")
    if source.duplicated(["ts_code", "period"]).any():
        raise ValueError("execution labels contain duplicate stock-months")
    result = source.rename(columns={"mark_return_1m": "return_m0"})
    for offset in (1, 2):
        lookup = source.assign(period=source["period"] - offset).rename(
            columns={"mark_return_1m": f"return_m{offset}"}
        )[["ts_code", "period", f"return_m{offset}"]]
        result = result.merge(lookup, on=["ts_code", "period"], how="left", validate="one_to_one")
    cumulative = 1.0 + result["return_m0"]
    for column in ("return_m1", "return_m2"):
        value = result[column]
        value = value.mask(value.isna() & cumulative.le(1e-12), 0.0)
        cumulative = cumulative * (1.0 + value)
    result["stock_return_3m"] = cumulative - 1.0
    if "entry_tradable" in result:
        result["stock_return_3m"] = result["stock_return_3m"].where(
            result["entry_tradable"].fillna(False)
        )
    return result[["signal_date", "ts_code", "stock_return_3m"]]


def forward_industry_returns(members: pd.DataFrame, execution_labels: pd.DataFrame) -> pd.DataFrame:
    returns = stock_forward_return_3m(execution_labels)
    panel = members.merge(returns, on=["signal_date", "ts_code"], how="left", validate="one_to_one")
    rows = []
    for (signal_date, industry), group in panel.groupby(["signal_date", "l1_code"], sort=True):
        total_weight = group["benchmark_weight"].sum()
        valid = group["stock_return_3m"].notna() & group["benchmark_weight"].gt(0)
        valid_weight = group.loc[valid, "benchmark_weight"].sum()
        coverage = float(valid_weight / total_weight) if total_weight > 0 else float("nan")
        value = float(
            np.average(group.loc[valid, "stock_return_3m"], weights=group.loc[valid, "benchmark_weight"])
        ) if valid.any() and coverage >= 0.95 else float("nan")
        rows.append({"signal_date": signal_date, "l1_code": industry, "industry_return_3m": value, "return_weight_coverage": coverage})
    return pd.DataFrame(rows)


def monthly_rank_ic(frame: pd.DataFrame, signal: str, future_return: str) -> pd.Series:
    return frame.groupby("signal_date", sort=True).apply(
        lambda group: group[signal].corr(group[future_return], method="spearman"),
        include_groups=False,
    ).dropna()


def monthly_partial_rank_ic(
    frame: pd.DataFrame,
    signal: str,
    future_return: str,
    control: str,
) -> pd.Series:
    def one_month(group: pd.DataFrame) -> float:
        valid = group[[signal, future_return, control]].dropna()
        if len(valid) < 5:
            return float("nan")
        x = valid[control].rank(pct=True).to_numpy()
        y = valid[signal].rank(pct=True).to_numpy()
        design = np.column_stack([np.ones(len(x)), x])
        residual = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
        if np.std(residual) <= 1e-12:
            return float("nan")
        return float(pd.Series(residual).corr(valid[future_return].rank(pct=True).reset_index(drop=True)))

    return frame.groupby("signal_date", sort=True).apply(one_month, include_groups=False).dropna()


def industry_tilts(scores: pd.DataFrame) -> pd.DataFrame:
    required = {"signal_date", "l1_code", "industry_earnings_diffusion"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"scores missing columns: {sorted(missing)}")
    rows = []
    cohorts: list[tuple[pd.Period, pd.Series]] = []
    for signal_date, month in scores.groupby("signal_date", sort=True):
        period = pd.Timestamp(signal_date).to_period("M")
        cohorts = [(started, cohort) for started, cohort in cohorts if period.ordinal - started.ordinal <= 2]
        valid = month.dropna(subset=["industry_earnings_diffusion"]).set_index("l1_code")
        if not valid.empty:
            rank = valid["industry_earnings_diffusion"].rank(method="average")
            centered = rank - rank.mean()
            if centered.abs().sum() > 0:
                cohorts.append((period, centered / centered.abs().sum() * 0.10))
        if not cohorts:
            continue
        combined = pd.concat([cohort for _, cohort in cohorts], axis=1).fillna(0.0).mean(axis=1)
        combined = combined - combined.mean()
        combined = combined / combined.abs().sum() * 0.10
        if combined.abs().max() > 0.02 + 1e-12:
            raise ValueError("industry active cap cannot be satisfied by fixed rank mapping")
        rows.extend(
            {"signal_date": signal_date, "l1_code": industry, "industry_tilt": float(value)}
            for industry, value in combined.items()
        )
    return pd.DataFrame(rows)


def aggregate_industry_diffusion(
    members: pd.DataFrame,
    financial_signal: pd.DataFrame,
    analyst_signal: pd.DataFrame,
) -> pd.DataFrame:
    required = {"signal_date", "ts_code", "l1_code", "total_mv"}
    missing = required - set(members.columns)
    if missing:
        raise ValueError(f"member data missing columns: {sorted(missing)}")
    panel = members.merge(
        financial_signal,
        on=["signal_date", "ts_code"],
        how="left",
        validate="one_to_one",
    ).merge(
        analyst_signal[["signal_date", "ts_code", "earnings_revision"]],
        on=["signal_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    rows = []
    for (signal_date, industry), group in panel.groupby(["signal_date", "l1_code"], sort=True):
        row: dict[str, object] = {
            "signal_date": signal_date,
            "l1_code": industry,
            "member_count": int(group["ts_code"].nunique()),
        }
        for source, output in (
            ("revenue_acceleration", "positive_revenue_acceleration_share"),
            ("deducted_profit_acceleration", "positive_deducted_profit_acceleration_share"),
            ("roe_improvement", "positive_roe_improvement_share"),
        ):
            valid = winsorize_company_values(group[source]).dropna()
            row[output] = float(valid.gt(0).mean()) if len(valid) else float("nan")
            row[f"{source}_companies"] = int(len(valid))
            row[f"{source}_company_coverage"] = float(len(valid) / row["member_count"]) if row["member_count"] else 0.0
            if len(valid) < 5 or row[f"{source}_company_coverage"] < 0.50:
                row[output] = float("nan")
        winsorized_revision = winsorize_company_values(group["earnings_revision"])
        revision_valid = winsorized_revision.notna()
        row["earnings_revision_weighted_median"] = weighted_median(
            winsorized_revision, group["total_mv"]
        )
        row["earnings_revision_companies"] = int(revision_valid.sum())
        total_cap = pd.to_numeric(group["total_mv"], errors="coerce").sum(min_count=1)
        covered_cap = pd.to_numeric(group.loc[revision_valid, "total_mv"], errors="coerce").sum(min_count=1)
        row["earnings_revision_market_cap_coverage"] = float(covered_cap / total_cap) if total_cap and total_cap > 0 else float("nan")
        if row["earnings_revision_companies"] < 5 or row["earnings_revision_market_cap_coverage"] < 0.20:
            row["earnings_revision_weighted_median"] = float("nan")
        rows.append(row)
    result = pd.DataFrame(rows)
    component_columns = [
        "positive_revenue_acceleration_share",
        "positive_deducted_profit_acceleration_share",
        "positive_roe_improvement_share",
        "earnings_revision_weighted_median",
    ]
    for column in component_columns:
        result[f"{column}_z"] = result.groupby("signal_date")[column].transform(
            lambda values: (values - values.mean()) / values.std(ddof=0) if values.notna().sum() > 1 and values.std(ddof=0) > 0 else np.nan
        )
    z_columns = [f"{column}_z" for column in component_columns]
    result["industry_earnings_diffusion"] = result[z_columns].mean(axis=1, skipna=False)
    return result
