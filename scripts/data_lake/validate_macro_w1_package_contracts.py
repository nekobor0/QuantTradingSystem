from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


EXPECTED = {"rates_liquidity": 11, "pmi_state": 8, "prices": 5, "money_credit": 8, "growth_output": 3, "global_financial_conditions": 9}
COMMON_DECISIONS = {f"W1_D{number}" for number in range(1, 10)}
MONEY_DECISIONS = COMMON_DECISIONS | {"W1_D10", "W1_D11"}
GLOBAL_DECISIONS = {f"GFC_D{number}" for number in range(1, 5)}
MONEY_RETIRED = {"CN.LOANS.RMB.FLOW", "CN.LOANS.CORP.MEDIUM_LONG.FLOW"}


def validate_contracts(contract_root: Path, registry_path: Path) -> dict[str, object]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registered = {item["canonical_id"]: item for item in registry["series"]}
    sources = set(registry["sources"])
    contracts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(contract_root.glob("*.json"))]
    package_counts = Counter()
    contract_series: list[str] = []
    checks = {
        "six_contracts": len(contracts) == 6,
        "package_ids_exact": {item["package_id"] for item in contracts} == set(EXPECTED),
        "all_schema_v2": all(item["schema_version"] == 2 for item in contracts),
        "all_states_expected": all(
            item["status"].startswith("GOLD_")
            if item["package_id"] != "global_financial_conditions"
            else item["status"] == "CONTRACT_FROZEN_OFFICIAL_EVIDENCE_NOT_ACQUIRED"
            for item in contracts
        ),
        "all_decisions_frozen": all(
            set(item["accepted_decisions"])
            == (
                MONEY_DECISIONS
                if item["package_id"] == "money_credit"
                else GLOBAL_DECISIONS
                if item["package_id"] == "global_financial_conditions"
                else COMMON_DECISIONS
            )
            for item in contracts
        ),
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
    money = next(item for item in contracts if item["package_id"] == "money_credit")
    money_by_id = {item["series_id"]: item for item in money["series"]}
    scope = money.get("canonical_scope_policy", {})
    checks["money_active_required_scope_exact"] = (
        money.get("status") == "GOLD_READY_ACTIVE_6_OF_6"
        and money.get("gold_coverage", {}).get("required_count") == 6
        and money.get("gold_coverage", {}).get("missing_series") == []
        and set(scope.get("retired_not_required", [])) == MONEY_RETIRED
        and scope.get("tombstones_retained") is True
        and scope.get("derived_replacement_implemented") is False
        and scope.get("cumulative_differencing_allowed") is False
        and scope.get("balance_differencing_allowed") is False
        and scope.get("aliases_forbidden") == {"CN.LOANS.RMB.FLOW": ["CN.TSF.RMB_LOANS.FLOW"]}
        and all(
            money_by_id[series_id].get("required") is False
            and money_by_id[series_id].get("implementation") == "RETIRED_NOT_REQUIRED_NO_DIRECT_MONTHLY_OBSERVATION"
            for series_id in MONEY_RETIRED
        )
    )
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
