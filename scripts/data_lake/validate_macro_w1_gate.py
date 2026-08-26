"""Validate the W1 pre-confirmation registry against the archived macro universe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def validate(registry_path: Path, universe_path: Path) -> dict[str, object]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    rows = registry["series"]
    ids = [row["id"] for row in rows]
    canonical_ids = [row["canonical_id"] for row in rows]
    package_counts = {package["package_id"]: package["series_count"] for package in registry["packages"]}
    actual_counts = {package_id: sum(row["package"] == package_id for row in rows) for package_id in package_counts}
    universe_by_id = {row["id"]: row for row in universe["series"]}
    decision_ids = [row["id"] for row in registry["confirmation_decisions"]]
    checks = {
        "declared_count_is_34": registry["series_count"] == 34,
        "exactly_34_series": len(rows) == 34,
        "unique_ids": len(ids) == len(set(ids)),
        "unique_canonical_ids": len(canonical_ids) == len(set(canonical_ids)),
        "all_ids_in_constitution_backlog": set(ids).issubset(universe_by_id),
        "package_counts_match": actual_counts == package_counts,
        "known_sources_only": set(row["source"] for row in rows).issubset(registry["sources"]),
        "existing_assets_are_crosschecks": registry["policies"]["existing_tushare_role"] == "independent_crosscheck_only",
        "all_decisions_confirmed": (
            registry["status"] == "DECISIONS_CONFIRMED"
            and registry["policies"]["human_confirmation_complete"]
            and not registry["policies"]["no_full_backfill_before_human_confirmation"]
            and registry["confirmed_decision_ids"] == [f"W1_D{number}" for number in range(1, 10)]
            and decision_ids == registry["confirmed_decision_ids"]
        ),
        "rates_remain_shadow_only": registry["policies"]["rates_shadow_only_before_sol_review"],
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {"passed": not failures, "checks": checks, "failures": failures, "package_counts": actual_counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/macro_w1_confirmation_registry.json"))
    parser.add_argument("--universe", type=Path, default=Path("development/18-macro-data-layer/R011_macro_data_prioritization/02_china_macro_data_universe_v0.1.yaml"))
    args = parser.parse_args()
    result = validate(args.registry, args.universe)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
