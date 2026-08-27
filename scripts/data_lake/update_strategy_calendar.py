"""Extend an SSE strategy calendar from a versioned official schedule.

The output is a derived calendar, not evidence that a session actually traded.
Run after the market close and cap ``--through`` at the latest completed day.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = ("exchange", "cal_date", "is_open", "pretrade_date")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _date_key(value: str) -> str:
    return date.fromisoformat(value.replace("/", "-")).strftime("%Y%m%d")


def extend_calendar(base: pd.DataFrame, rules: dict[str, Any], through: str) -> pd.DataFrame:
    missing = set(REQUIRED_COLUMNS) - set(base.columns)
    if missing:
        raise ValueError(f"calendar missing columns: {sorted(missing)}")
    exchange = str(rules["exchange"])
    frame = base.loc[base["exchange"].astype(str).eq(exchange), list(REQUIRED_COLUMNS)].copy()
    if frame.empty:
        raise ValueError(f"calendar has no {exchange} rows")
    frame["cal_date"] = frame["cal_date"].astype(str).str.replace("-", "", regex=False)
    frame["is_open"] = frame["is_open"].astype(str)
    frame["pretrade_date"] = frame["pretrade_date"].astype(str).str.replace("-", "", regex=False)
    if frame.duplicated(["exchange", "cal_date"]).any():
        raise ValueError("calendar has duplicate exchange/cal_date keys")

    through_key = _date_key(through)
    valid_from = _date_key(str(rules["valid_from"]))
    valid_to = _date_key(str(rules["valid_to"]))
    current_max = frame["cal_date"].max()
    if not valid_from <= through_key <= valid_to:
        raise ValueError(f"through={through_key} is outside rule coverage {valid_from}..{valid_to}")
    if through_key <= current_max:
        return frame.sort_values("cal_date").reset_index(drop=True)

    closed = {_date_key(str(item)) for item in rules["closed_dates"]}
    prior_open = frame.loc[frame["is_open"].eq("1"), "cal_date"].max()
    rows: list[dict[str, str]] = []
    cursor = datetime.strptime(current_max, "%Y%m%d").date() + timedelta(days=1)
    end_date = datetime.strptime(through_key, "%Y%m%d").date()
    while cursor <= end_date:
        key = cursor.strftime("%Y%m%d")
        is_open = "1" if cursor.weekday() < 5 and key not in closed else "0"
        rows.append({
            "exchange": exchange,
            "cal_date": key,
            "is_open": is_open,
            "pretrade_date": prior_open,
        })
        if is_open == "1":
            prior_open = key
        cursor += timedelta(days=1)
    result = pd.concat([frame, pd.DataFrame(rows)], ignore_index=True)
    return result.sort_values("cal_date").reset_index(drop=True)


def update_calendar(base_path: Path, rules_path: Path, output_path: Path, through: str) -> dict[str, Any]:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    base = pd.read_parquet(base_path)
    result = extend_calendar(base, rules, through)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exchange": rules["exchange"],
        "source_kind": "official_schedule_derived_calendar",
        "actual_session_evidence": False,
        "base": {"path": str(base_path.resolve()), "sha256": _sha256(base_path)},
        "rules": {"path": str(rules_path.resolve()), "sha256": _sha256(rules_path), "source": rules["source"]},
        "output": {"path": str(output_path.resolve()), "sha256": _sha256(output_path)},
        "coverage": {
            "min": str(result["cal_date"].min()),
            "max": str(result["cal_date"].max()),
            "rows": int(len(result)),
            "open_sessions": int(result["is_open"].astype(str).eq("1").sum()),
            "derived_through": _date_key(through),
        },
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=Path("config/sse_trading_calendar_rules.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through", required=True, help="Latest completed market date, YYYY-MM-DD")
    args = parser.parse_args()
    print(json.dumps(update_calendar(args.base, args.rules, args.output, args.through), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
