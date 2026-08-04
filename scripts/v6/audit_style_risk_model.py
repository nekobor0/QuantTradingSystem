"""Audit the frozen V5 panel against the complete V6 style-risk schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.v6.baseline_registry import sha256_file
from quant_trading_system.research.v6.style_risk import audit_style_risk_panel
from quant_trading_system.research.v6.style_risk import financial_group_panel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--panel",
        type=Path,
        default=Path("artifacts/alpha_phase1/factor_panel_style_baseline_v5.parquet"),
    )
    parser.add_argument(
        "--industry-members",
        type=Path,
        default=Path("artifacts/alpha_phase1/tushare/index_members_sw2021.parquet"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/data_audits/style_risk_model_v6.json"),
    )
    args = parser.parse_args()
    panel = pd.read_parquet(args.panel)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    members = pd.read_parquet(args.industry_members)
    groups = financial_group_panel(
        members,
        sorted(pd.Timestamp(value) for value in panel["signal_date"].unique()),
    )
    panel = panel.drop(columns=["financial_sector"]).merge(
        groups,
        on=["ts_code", "signal_date"],
        how="left",
        validate="one_to_one",
    )
    audit = audit_style_risk_panel(panel)
    audit["source"] = {
        "path": args.panel.as_posix(),
        "sha256": sha256_file(args.panel),
    }
    audit["industry_membership_source"] = {
        "path": args.industry_members.as_posix(),
        "sha256": sha256_file(args.industry_members),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "rows": audit["rows"],
                "controls": len(audit["schema"]["continuous_controls"]),
                "pit_violations": audit["pit_violations"],
            }
        )
    )


if __name__ == "__main__":
    main()
