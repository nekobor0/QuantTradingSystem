"""Write checksum manifests for ignored local W1 gold source files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    registry = json.loads((ROOT / "config" / "macro_w1_gold_registry.json").read_text(encoding="utf-8"))
    for package_id, spec in registry["packages"].items():
        if package_id == "rates_liquidity":
            continue
        raw_names = [name for name in spec["required_files"] if name not in {"expected.json", "checksums.json"}]
        for fixture_id in spec["fixtures"]:
            period_root = ROOT / spec["fixture_root"] / fixture_id
            if not all((period_root / name).is_file() for name in raw_names):
                continue
            payload = {
                "algorithm": "sha256",
                "files": {name: hashlib.sha256((period_root / name).read_bytes()).hexdigest() for name in raw_names},
            }
            (period_root / "checksums.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
