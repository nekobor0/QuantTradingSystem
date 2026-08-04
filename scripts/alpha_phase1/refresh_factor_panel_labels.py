"""Refresh shared execution labels in derived factor panels atomically."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


KEYS = ["ts_code", "signal_date"]
LABELS = ["forward_return", "forward_return_delay2", "entry_1_tradable", "exit_1_tradable"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--panel", type=Path, action="append", required=True)
    args = parser.parse_args()

    labels = pd.read_parquet(args.base_panel, columns=[*KEYS, *LABELS])
    if labels.duplicated(KEYS).any():
        raise ValueError("base panel contains duplicate keys")
    for path in args.panel:
        frame = pd.read_parquet(path).drop(columns=LABELS, errors="ignore")
        refreshed = frame.merge(labels, on=KEYS, how="left", validate="one_to_one")
        temporary = path.with_suffix(path.suffix + ".tmp")
        refreshed.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
        print({"panel": str(path), "rows": len(refreshed)})


if __name__ == "__main__":
    main()
