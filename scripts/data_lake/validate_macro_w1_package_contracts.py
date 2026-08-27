from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


EXPECTED = {"rates_liquidity": 11, "pmi_state": 8, "prices": 5, "money_credit": 7, "growth_output": 3}
DECISIONS = {f"W1_D{number}" for number in range(1, 10)}


def validate_contracts(contract_root: Path, registry_path: Path) -> dict[str, object]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registered = {item["canonical_id"]: item for item in registry["series"]}
    sources = set(registry["sources"])
    contracts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(contract_root.glob("*.json"))]
    package_counts = Counter()
    contract_series: list[str] = []
    checks = {
        "five_contracts": len(contracts) == 5,
        "package_ids_exact": {item["package_id"] for item in contracts} == set(EXPECTED),
        "all_schema_v2": all(item["schema_version"] == 2 for item in contracts),
        "all_gold_pending": all(item["status"] == "CONTRACT_FROZEN_GOLD_PENDING" for item in contracts),
        "all_decisions_frozen": all(set(item["accepted_decisions"]) == DECISIONS for item in contracts),
        "source_whitelists_registered": all(set(item["source_whitelist"]).issubset(sources) for item in contracts),
    }
    metadata_ok = True
    for contract in contracts:
        package_counts[contract["package_id"]] += len(contract["series"])
        for item in contract["series"]:
            contract_series.append(item["series_id"])
            metadata_ok &= all(item.get(field) for field in (
                "source", "frequency", "unit", "measure_basis", "pit_grade", "license_scope", "implementation"
            ))
            metadata_ok &= item["source"] in contract["source_whitelist"]
    checks["package_counts_exact"] = dict(package_counts) == EXPECTED
    checks["series_union_exact"] = set(contract_series) == set(registered) and len(contract_series) == len(set(contract_series))
    checks["series_metadata_complete"] = bool(metadata_ok)
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {"passed": not failures, "checks": checks, "failures": failures, "package_counts": dict(package_counts)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", type=Path, default=Path("config/macro_w1_packages"))
    parser.add_argument("--registry", type=Path, default=Path("config/macro_w1_confirmation_registry.json"))
    args = parser.parse_args()
    result = validate_contracts(args.contracts, args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
