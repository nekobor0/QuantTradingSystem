"""V6 style-risk schema and portfolio exposure audit."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


STYLE_CONTROLS_V6 = (
    "size",
    "nonlinear_size",
    "beta",
    "momentum",
    "short_reversal",
    "liquidity",
    "residual_volatility",
    "value_composite",
    "investment",
    "quality_composite",
    "leverage",
    "loss_dummy",
)
KEYS = ("ts_code", "signal_date")
CATEGORICAL_CONTROLS = ("l1_code", "financial_sector")
REQUIRED_FINANCIAL_GROUPS = {
    "nonfinancial",
    "bank",
    "broker",
    "insurance",
}
FINANCIAL_L2_GROUPS = {
    "801193.SI": "broker",
    "801194.SI": "insurance",
    "801191.SI": "other_nonbank_financial",
}


def financial_group_panel(
    members: pd.DataFrame, dates: list[pd.Timestamp]
) -> pd.DataFrame:
    """Build PIT bank/broker/insurance groups from SW2021 membership history."""
    required = {"ts_code", "l1_code", "l2_code", "in_date", "out_date"}
    missing = required.difference(members.columns)
    if missing:
        raise ValueError(f"industry membership missing columns: {sorted(missing)}")
    source = members.copy()
    source["in_date"] = source["in_date"].fillna("").astype(str)
    source["out_date"] = source["out_date"].fillna("").astype(str)
    rows = []
    for date in dates:
        text = date.strftime("%Y%m%d")
        active = source[
            source["in_date"].le(text)
            & (source["out_date"].eq("") | source["out_date"].gt(text))
        ]
        active = active.sort_values(
            ["ts_code", "in_date", "l1_code", "l2_code"]
        ).drop_duplicates("ts_code", keep="last")
        groups = np.select(
            [
                active["l1_code"].eq("801780.SI"),
                active["l2_code"].eq("801193.SI"),
                active["l2_code"].eq("801194.SI"),
                active["l2_code"].eq("801191.SI"),
            ],
            ["bank", "broker", "insurance", "other_nonbank_financial"],
            default="nonfinancial",
        )
        rows.append(
            active[["ts_code"]].assign(
                signal_date=date,
                financial_sector=groups,
            )
        )
    return pd.concat(rows, ignore_index=True)


def validate_style_risk_panel(panel: pd.DataFrame) -> None:
    required = {*KEYS, *STYLE_CONTROLS_V6, *CATEGORICAL_CONTROLS, "report_age_days"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"missing V6 style-risk columns: {sorted(missing)}")
    if panel.duplicated(list(KEYS)).any():
        raise ValueError("duplicate V6 style-risk keys")
    if panel["signal_date"].isna().any():
        raise ValueError("missing signal_date in V6 style-risk panel")
    pit_rows = panel["quality_composite"].notna() | panel["leverage"].notna()
    invalid_age = pit_rows & (
        panel["report_age_days"].isna()
        | panel["report_age_days"].lt(0)
        | panel["report_age_days"].gt(250)
    )
    if invalid_age.any():
        raise ValueError("quarterly style exposure violates 250-day PIT carry rule")


def portfolio_style_exposure(
    weights: pd.Series,
    cross_section: pd.DataFrame,
) -> dict[str, Any]:
    """Return weighted style exposures and coverage without silently renormalizing."""
    if cross_section["ts_code"].duplicated().any():
        raise ValueError("duplicate securities in style-risk cross-section")
    frame = cross_section.set_index("ts_code")
    portfolio = weights.astype(float)
    if (portfolio < -1e-12).any():
        raise ValueError("negative long-only portfolio weight")
    if not np.isclose(float(portfolio.sum()), 1.0, atol=1e-10):
        raise ValueError("portfolio weights must sum to one")
    output: dict[str, Any] = {"styles": {}, "coverage": {}, "industries": {}}
    for control in STYLE_CONTROLS_V6:
        values = frame[control].reindex(portfolio.index)
        valid = values.notna()
        output["coverage"][control] = float(portfolio[valid].sum())
        output["styles"][control] = (
            float((portfolio[valid] * values[valid]).sum()) if valid.any() else None
        )
    industries = frame["l1_code"].reindex(portfolio.index)
    valid_industry = industries.notna()
    output["coverage"]["l1_code"] = float(portfolio[valid_industry].sum())
    output["industries"] = {
        str(industry): float(weight)
        for industry, weight in portfolio[valid_industry].groupby(
            industries[valid_industry]
        ).sum().items()
    }
    sectors = frame["financial_sector"].reindex(portfolio.index)
    valid_sector = sectors.notna()
    output["coverage"]["financial_sector"] = float(portfolio[valid_sector].sum())
    output["financial_sectors"] = {
        str(sector): float(weight)
        for sector, weight in portfolio[valid_sector].groupby(
            sectors[valid_sector]
        ).sum().items()
    }
    return output


def audit_style_risk_panel(panel: pd.DataFrame) -> dict[str, Any]:
    validate_style_risk_panel(panel)
    active = panel["size"].notna()
    coverage = {
        control: float(panel.loc[active, control].notna().mean())
        for control in STYLE_CONTROLS_V6
    }
    monthly = panel.loc[active].groupby("signal_date")[list(STYLE_CONTROLS_V6)].agg(
        lambda values: values.notna().mean()
    )
    observed_financial_groups = set(panel["financial_sector"].dropna().astype(str))
    missing_financial_groups = sorted(
        REQUIRED_FINANCIAL_GROUPS.difference(observed_financial_groups)
    )
    return {
        "version": 6,
        "status": (
            "PASS" if not missing_financial_groups else "DATA_BLOCKED_PARTIAL"
        ),
        "schema": {
            "keys": list(KEYS),
            "continuous_controls": list(STYLE_CONTROLS_V6),
            "categorical_controls": list(CATEGORICAL_CONTROLS),
            "quarterly_pit_max_age_days": 250,
            "model_scope": (
                "style exposure and coverage model; not a Barra covariance model"
            ),
        },
        "rows": int(len(panel)),
        "signal_months": int(panel["signal_date"].nunique()),
        "symbols": int(panel["ts_code"].nunique()),
        "duplicate_keys": 0,
        "active_rows": int(active.sum()),
        "active_coverage": coverage,
        "monthly_active_coverage_min": {
            control: float(monthly[control].min()) for control in STYLE_CONTROLS_V6
        },
        "monthly_active_coverage_median": {
            control: float(monthly[control].median()) for control in STYLE_CONTROLS_V6
        },
        "pit_violations": 0,
        "financial_groups_observed": sorted(observed_financial_groups),
        "financial_groups_required": sorted(REQUIRED_FINANCIAL_GROUPS),
        "financial_groups_missing": missing_financial_groups,
        "blocking_reason": (
            None
            if not missing_financial_groups
            else "frozen panel aggregates brokers and insurers as nonbank_financial"
        ),
    }
