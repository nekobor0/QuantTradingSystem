"""Run the frozen R011 W1 DR007/R007 + OMO/MLF official shadow backfill."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from quant_trading_system.research.macro_data.backfill import run_rates_shadow_backfill


ROOT = Path(__file__).resolve().parents[2]


def _load_strategy_calendar(path: Path) -> frozenset[str]:
    trading_dates = frozenset(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    if not trading_dates:
        raise ValueError("strategy calendar is empty")
    for item in trading_dates:
        date.fromisoformat(item)
    return trading_dates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=ROOT / "config" / "macro_w1_rates_contract.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--start-date", default="2026-07-27")
    parser.add_argument("--end-date", default="2026-08-25")
    parser.add_argument("--sleep-seconds", type=float)
    parser.add_argument("--strategy-calendar", type=Path, required=True, help="UTF-8 file with one open strategy date per line; include a session after end-date")
    args = parser.parse_args()
    report = run_rates_shadow_backfill(
        registry_path=args.contract,
        output_root=args.output_root,
        start_date=args.start_date,
        strategy_trading_dates=_load_strategy_calendar(args.strategy_calendar),
        end_date=args.end_date,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
