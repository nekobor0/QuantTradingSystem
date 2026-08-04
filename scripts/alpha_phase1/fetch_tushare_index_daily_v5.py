"""Fetch the two frozen V5 benchmark index series without persisting credentials."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts

from fetch_tushare_research_data import load_token


INDEX_CODES = ("000300.SH", "000852.SH")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/alpha_phase1/tushare"))
    parser.add_argument("--start-date", default="20180101")
    parser.add_argument("--end-date", default="20260730")
    args = parser.parse_args()

    pro = ts.pro_api(load_token(args.config))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "api": "index_daily",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "datasets": {},
    }
    for code in INDEX_CODES:
        frame = pro.index_daily(
            ts_code=code, start_date=args.start_date, end_date=args.end_date
        )
        required = {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RuntimeError(f"{code}: missing fields {missing}")
        frame = frame.drop_duplicates(["ts_code", "trade_date"]).sort_values(
            ["ts_code", "trade_date"]
        )
        output = args.output_dir / f"index_daily_{code.replace('.', '_')}.parquet"
        temporary = output.with_suffix(output.suffix + ".tmp")
        frame.to_parquet(temporary, index=False)
        temporary.replace(output)
        manifest["datasets"][code] = {
            "rows": int(len(frame)),
            "date_min": str(frame["trade_date"].min()),
            "date_max": str(frame["trade_date"].max()),
            "duplicate_keys": int(frame.duplicated(["ts_code", "trade_date"]).sum()),
            "columns": list(frame.columns),
            "file": output.name,
        }
    manifest_path = args.output_dir / "index_daily_v5_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
