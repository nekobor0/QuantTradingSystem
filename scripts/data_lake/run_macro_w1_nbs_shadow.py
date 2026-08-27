"""Reparse the two official Gold periods for one NBS W1 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_execution import build_audit, validate_audit
from quant_trading_system.research.macro_data.w1_nbs import parse_growth, parse_pmi, parse_prices


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _keyed(rows: list[dict[str, object]]) -> dict[tuple[str, str], float]:
    return {(str(row["series_id"]), str(row["reference_period"])): float(row["value"]) for row in rows}


def _parse(package_id: str, root: Path, fixture_id: str) -> list[dict[str, object]]:
    if package_id == "pmi_state":
        return parse_pmi((root / "nbs_pmi.html").read_bytes(), fixture_id)
    if package_id == "prices":
        return parse_prices(
            (root / "nbs_cpi.html").read_bytes(), (root / "nbs_ppi.html").read_bytes(),
            (root / "nbs_interpretation.html").read_bytes(), fixture_id,
        )
    if package_id == "growth_output":
        return parse_growth((root / "nbs_gdp.html").read_bytes(), (root / "nbs_industrial.html").read_bytes(), fixture_id)
    raise ValueError(f"not an NBS Gold-ready package: {package_id}")


def run(package_id: str, output_root: Path) -> dict[str, object]:
    registry = _load(ROOT / "config" / "macro_w1_gold_registry.json")
    spec = registry["packages"][package_id]  # type: ignore[index]
    if spec["status"] != "GOLD_READY_SHADOW_ONLY":  # type: ignore[index]
        raise ValueError(f"package Gold is not ready: {package_id}")
    fixture_root = ROOT / str(spec["fixture_root"])  # type: ignore[index]
    observed: list[str] = []
    blockers: list[dict[str, str]] = []
    sources: list[dict[str, object]] = []
    for fixture_id in spec["fixtures"]:  # type: ignore[index]
        period_root = fixture_root / str(fixture_id)
        expected = _load(period_root / "expected.json")
        actual_rows = _parse(package_id, period_root, str(fixture_id))
        if _keyed(actual_rows) == _keyed(expected["rows"]):  # type: ignore[arg-type,index]
            observed.append(str(fixture_id))
        else:
            blockers.append({"code": "GOLD_MISMATCH", "detail": str(fixture_id)})
        checksums = _load(period_root / "checksums.json")["files"]
        sources.append({
            "fixture_id": fixture_id,
            "files": [{"name": name, "sha256": digest} for name, digest in checksums.items()],  # type: ignore[union-attr]
        })
    fixtures = [str(item) for item in spec["fixtures"]]  # type: ignore[index]
    audit = build_audit(
        package_id=package_id, run_mode="shadow", start=fixtures[0], end=fixtures[-1],
        expected=fixtures, observed=observed, sources=sources, blockers=blockers,
        unexplained_missing=[item for item in fixtures if item not in observed],
    )
    validation = validate_audit(audit)
    result = {"audit": audit, "validation": validation, "sol_gate_passed": validation["passed"] and not audit["blocked"]}
    output = output_root / "audits" / f"w1_{package_id}_shadow.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", choices=("pmi_state", "prices", "growth_output"), required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    result = run(args.package, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["sol_gate_passed"] else 1)


if __name__ == "__main__":
    main()
