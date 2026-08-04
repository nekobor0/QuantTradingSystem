"""Run two narrow Tushare pledge permission probes without persisting secrets."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts

from scripts.alpha_phase1.smoke_tushare_permissions import _load_token, _probe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    pro = ts.pro_api(_load_token(args.config))
    probes = {
        "pledge_stat": _probe(pro, "pledge_stat", ts_code="000001.SZ"),
        "pledge_detail": _probe(pro, "pledge_detail", ts_code="000001.SZ"),
    }
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tushare_version": ts.__version__,
        "probe_count": len(probes),
        "probes": probes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
