"""Validate ignored local W1 gold evidence without committing market data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
READY = "GOLD_READY_SHADOW_ONLY"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_package(package_id: str, spec: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    root = ROOT / spec["fixture_root"]
    expected_series = {item["series_id"] for item in contract["series"]}
    covered = set(spec.get("covered_series", expected_series))
    blocked = set(spec.get("blocked_series", []))
    checks: dict[str, bool] = {
        "coverage_partition_exact": covered | blocked == expected_series and not covered & blocked,
        "two_fixture_periods": len(spec["fixtures"]) == 2,
        "status_matches_coverage": (spec["status"] == READY) == (covered == expected_series),
    }
    periods: dict[str, Any] = {}
    required = set(spec.get("required_files", []))
    for fixture_id in spec["fixtures"]:
        period_root = root / fixture_id
        present = all((period_root / name).is_file() for name in required)
        period_checks: dict[str, bool] = {"required_files_present": present}
        if present:
            expected = _load(period_root / "expected.json")
            checksums = _load(period_root / "checksums.json")["files"]
            rows = expected["rows"]
            row_series = {row["series_id"] for row in rows}
            period_checks.update(
                {
                    "fixture_id_matches": expected["fixture_id"] == fixture_id,
                    "covered_series_exact": row_series == covered,
                    "unique_series": len(rows) == len(row_series),
                    "finite_numeric_values": all(isinstance(row["value"], (int, float)) for row in rows),
                    "source_files_present": all((period_root / row["source_file"]).is_file() for row in rows),
                    "checksums_complete": set(checksums) == {name for name in required if name not in {"expected.json", "checksums.json"}},
                    "raw_checksums_match": all((period_root / name).is_file() and _sha256(period_root / name) == digest for name, digest in checksums.items()),
                    "omissions_match_blocked": {item["series_id"] for item in expected.get("expected_omissions", [])} == blocked,
                }
            )
        periods[fixture_id] = period_checks
    failures = sorted(
        [name for name, passed in checks.items() if not passed]
        + [f"{period}:{name}" for period, values in periods.items() for name, passed in values.items() if not passed]
    )
    return {
        "package_id": package_id,
        "evidence_valid": not failures,
        "package_ready": not failures and spec["status"] == READY,
        "status": spec["status"],
        "checks": checks,
        "periods": periods,
        "failures": failures,
    }


def validate_registry(registry_path: Path) -> dict[str, Any]:
    registry = _load(registry_path)
    results: dict[str, Any] = {}
    for package_id, spec in registry["packages"].items():
        contract = _load(ROOT / "config" / "macro_w1_packages" / f"{package_id}.json")
        if package_id == "rates_liquidity":
            expected_series = {item["series_id"] for item in contract["series"]}
            covered = set(spec["covered_series"])
            blocked = set(spec["blocked_series"])
            results[package_id] = {
                "package_id": package_id,
                "evidence_valid": covered | blocked == expected_series and not covered & blocked,
                "package_ready": False,
                "status": spec["status"],
                "checks": {"coverage_partition_exact": covered | blocked == expected_series and not covered & blocked},
                "periods": {},
                "failures": [],
            }
        else:
            results[package_id] = validate_package(package_id, spec, contract)
    invalid = sorted(key for key, value in results.items() if not value["evidence_valid"])
    return {
        "passed": not invalid,
        "ready_packages": sorted(key for key, value in results.items() if value["package_ready"]),
        "blocked_packages": sorted(key for key, value in results.items() if not value["package_ready"]),
        "invalid_packages": invalid,
        "packages": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=ROOT / "config" / "macro_w1_gold_registry.json")
    args = parser.parse_args()
    result = validate_registry(args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
