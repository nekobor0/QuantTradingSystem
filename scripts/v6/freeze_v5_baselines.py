"""Create or verify the deterministic V6 registry of frozen V5 baselines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_trading_system.research.v6.baseline_registry import (
    assert_registry_matches,
    build_registry_snapshot,
    write_registry_atomic,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--goal",
        type=Path,
        default=Path("development/16-alpha-factor-phase1/GOAL_V6.md"),
    )
    parser.add_argument(
        "--evaluator-spec",
        type=Path,
        default=Path(
            "development/16-alpha-factor-phase1/PORTFOLIO_EVALUATOR_V5_SPEC.md"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/registrations/v5_baselines_v6.json"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    snapshot = build_registry_snapshot(
        args.project_root.resolve(),
        args.goal.resolve(),
        args.evaluator_spec.resolve(),
    )
    if args.check:
        expected = json.loads(args.output.read_text(encoding="utf-8"))
        assert_registry_matches(expected, snapshot)
        print(json.dumps({"status": "PASS", "baselines": len(snapshot["baselines"])}))
        return
    write_registry_atomic(snapshot, args.output)
    print(json.dumps({"status": "CREATED", "baselines": len(snapshot["baselines"])}))


if __name__ == "__main__":
    main()

