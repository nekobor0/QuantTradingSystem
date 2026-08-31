from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


EXPECTED_PACKAGES = {
    "rates_liquidity": 11,
    "pmi_state": 8,
    "prices": 5,
    "money_credit": 8,
    "growth_output": 3,
    "global_financial_conditions": 9,
}


def validate_inventory(path: Path) -> dict[str, object]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    series = registry["series"]
    ids = [item["id"] for item in series]
    canonical_ids = [item["canonical_id"] for item in series]
    package_counts = Counter(item["package"] for item in series)
    states = Counter(item["state"] for item in series)
    summary = registry["inventory_summary"]
    advanced = (
        set(summary["formal_v1_series"])
        | set(summary["official_event_history_research_blocked"])
        | set(summary["shadow_blocked"])
    )
    global_by_id = {
        item["canonical_id"]: item for item in series if item["package"] == "global_financial_conditions"
    }
    checks = {
        "version_2": registry["version"] == 2,
        "series_44": len(series) == 44,
        "ids_unique": len(ids) == len(set(ids)),
        "canonical_ids_unique": len(canonical_ids) == len(set(canonical_ids)),
        "package_counts_exact": dict(package_counts) == EXPECTED_PACKAGES,
        "summary_total_exact": summary["w1_series_total"] == len(series),
        "formal_count_5": len(summary["formal_v1_series"]) == 5,
        "advanced_series_registered": advanced.issubset(canonical_ids),
        "not_formally_implemented_39": summary["not_formally_implemented_count"] == 39,
        "canonical_v2_available": summary["canonical_v2_available"] is True,
        "global_gold_7_of_9_exact": all(
            global_by_id[series_id]["state"] == "GOLD_READY_FROZEN_CANDIDATE_PIT_C"
            for series_id in (
                "US.EFFR", "US.SOFR", "US.TREASURY.3M", "US.TREASURY.2Y",
                "US.TREASURY.10Y", "US.TIPS.REAL.10Y", "US.BROAD_DOLLAR",
            )
        )
        and global_by_id["USD.CNY"]["state"] == "OFFICIAL_PRODUCT_CONFIRMED_ENTITLEMENT_BLOCKED"
        and global_by_id["USD.CNH"]["state"] == "SOURCE_AND_ENTITLEMENT_BLOCKED",
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "package_counts": dict(package_counts),
        "state_counts": dict(states),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/macro_w1_confirmation_registry.json"))
    args = parser.parse_args()
    result = validate_inventory(args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
