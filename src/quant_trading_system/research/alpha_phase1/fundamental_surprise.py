"""Point-in-time quarterly financial transformations for V4 research."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.style_baseline import winsorized_zscore


FINANCIAL_FIELDS = [
    "roe", "roe_waa", "grossprofit_margin", "netprofit_margin", "ocf_to_or",
    "ocf_to_profit", "debt_to_assets", "q_sales_yoy", "q_profit_yoy",
]


def prepare_versions(raw: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate disclosure versions and attach the then-known previous quarter."""
    frame = raw.copy().reset_index(drop=False).rename(columns={"index": "source_order"})
    frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "ann_date", "end_date"])
    update_flag = frame["update_flag"] if "update_flag" in frame else pd.Series(0, index=frame.index)
    frame["update_order"] = pd.to_numeric(update_flag, errors="coerce").fillna(0)
    frame = frame.sort_values(
        ["ts_code", "end_date", "ann_date", "update_order", "source_order"], kind="stable"
    ).drop_duplicates(["ts_code", "end_date", "ann_date"], keep="last")
    frame = frame.reset_index(drop=True)
    frame["version_id"] = np.arange(len(frame))
    frame["previous_end_date"] = frame["end_date"] - pd.offsets.QuarterEnd()

    available_fields = [column for column in FINANCIAL_FIELDS if column in frame]
    prior = frame[["ts_code", "end_date", "ann_date", *available_fields]].rename(
        columns={
            "end_date": "previous_end_date",
            "ann_date": "previous_ann_date",
            **{column: f"previous_{column}" for column in available_fields},
        }
    )
    candidates = frame.merge(prior, on=["ts_code", "previous_end_date"], how="left")
    candidates = candidates[
        candidates["previous_ann_date"].isna()
        | (candidates["previous_ann_date"] <= candidates["ann_date"])
    ]
    candidates = candidates.sort_values(
        ["version_id", "previous_ann_date"], kind="stable", na_position="first"
    ).drop_duplicates("version_id", keep="last")
    missing_ids = frame.loc[~frame["version_id"].isin(candidates["version_id"])]
    if not missing_ids.empty:
        missing_ids = missing_ids.copy()
        missing_ids["previous_ann_date"] = pd.NaT
        for column in available_fields:
            missing_ids[f"previous_{column}"] = np.nan
        candidates = pd.concat([candidates, missing_ids], ignore_index=True, sort=False)
    for column in ("q_profit_yoy", "q_sales_yoy", "ocf_to_or"):
        previous = f"previous_{column}"
        if column in candidates and previous in candidates:
            candidates[f"{column}_acceleration"] = candidates[column] - candidates[previous]
    return candidates.sort_values(["ts_code", "ann_date", "end_date"]).reset_index(drop=True)


def monthly_point_in_time(
    versions: pd.DataFrame, signal_dates: list[pd.Timestamp]
) -> pd.DataFrame:
    """Select the latest disclosed version of the latest report at each month end."""
    rows = []
    for signal_date in signal_dates:
        visible = versions[versions["ann_date"] <= signal_date]
        latest_versions = visible.sort_values(["ts_code", "end_date", "ann_date"]).drop_duplicates(
            ["ts_code", "end_date"], keep="last"
        )
        latest_reports = latest_versions.sort_values(["ts_code", "end_date"]).drop_duplicates(
            "ts_code", keep="last"
        )
        rows.append(latest_reports.assign(signal_date=signal_date))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def grouped_standardize(values: pd.Series, groups: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    for _, indices in groups.groupby(groups, dropna=False).groups.items():
        valid = values.loc[indices].dropna()
        if len(valid) >= 20:
            result.loc[valid.index] = winsorized_zscore(valid)
    return result


def residualize_surprise(frame: pd.DataFrame, surprise: pd.Series) -> pd.Series:
    """Residualize surprise on observed price response and frozen common styles by month."""
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    controls = ["announcement_return", "size", "value_composite", "momentum"]
    for _, indices in frame.groupby("signal_date", sort=False).groups.items():
        valid = surprise.loc[indices].notna() & frame.loc[indices, controls].notna().all(axis=1)
        sample_indices = pd.Index(indices)[valid.to_numpy()]
        if len(sample_indices) < 100:
            continue
        y = winsorized_zscore(surprise.loc[sample_indices])
        x = np.column_stack(
            [
                np.ones(len(sample_indices)),
                *[
                    winsorized_zscore(frame.loc[sample_indices, column]).to_numpy()
                    for column in controls
                ],
            ]
        )
        output.loc[sample_indices] = y.to_numpy() - x @ np.linalg.lstsq(
            x, y.to_numpy(), rcond=None
        )[0]
    return output


def announcement_returns(
    adjusted_close: pd.Series,
    announcement_dates: pd.Series,
    signal_dates: pd.Series,
) -> pd.Series:
    """Return from the last close before disclosure through the signal-date close."""
    prices = adjusted_close.dropna().sort_index()
    dates = prices.index.to_numpy(dtype="datetime64[ns]")
    values = prices.to_numpy(dtype=float)
    result = []
    for announcement, signal in zip(announcement_dates, signal_dates):
        if pd.isna(announcement) or pd.isna(signal) or signal < announcement:
            result.append(np.nan)
            continue
        start = dates.searchsorted(np.datetime64(announcement), side="left") - 1
        end = dates.searchsorted(np.datetime64(signal), side="right") - 1
        if start < 0 or end <= start:
            result.append(np.nan)
        else:
            result.append(values[end] / values[start] - 1)
    return pd.Series(result, index=announcement_dates.index, dtype=float)
