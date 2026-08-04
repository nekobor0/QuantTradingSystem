"""Append one validated V6 live-shadow record or correction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_trading_system.research.v6.live_shadow import (
    append_shadow_correction,
    append_shadow_record,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifacts/live_shadow"))
    parser.add_argument("--record", type=Path)
    parser.add_argument("--correction", type=Path)
    args = parser.parse_args()
    if bool(args.record) == bool(args.correction):
        raise ValueError("provide exactly one of --record or --correction")
    if args.record:
        payload = json.loads(args.record.read_text(encoding="utf-8"))
        output = append_shadow_record(args.root, payload)
    else:
        payload = json.loads(args.correction.read_text(encoding="utf-8"))
        output = append_shadow_correction(args.root, **payload)
    print(json.dumps({"status": "APPENDED", "path": output.as_posix()}))


if __name__ == "__main__":
    main()

