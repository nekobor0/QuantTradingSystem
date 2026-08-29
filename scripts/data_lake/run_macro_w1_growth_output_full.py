"""Gate-protected formal writer for the frozen 581-row growth_output candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import write_canonical_v2_snapshot  # noqa: E402
from scripts.data_lake.validate_macro_w1_full_entry import (  # noqa: E402
    GROWTH_END,
    GROWTH_FORMAL_INPUT,
    GROWTH_START,
    check_growth_full_gate_v2,
)
from scripts.data_lake.validate_macro_w1_growth_output_full_candidate import validate_manual_candidate  # noqa: E402


DEFAULT_MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"
CURATED_NAME = Path(GROWTH_FORMAL_INPUT["formal_curated"]).name


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _blocked(output_root: Path, blockers: list[dict[str, str]]) -> dict[str, Any]:
    curated = output_root / GROWTH_FORMAL_INPUT["formal_curated"]
    digest = _sha256(curated)
    return {
        "blocked": True,
        "blockers": blockers,
        "curated_path": str(curated),
        "curated_exists": curated.exists(),
        "curated_sha256_before": digest,
        "curated_sha256_after": digest,
        "research_ready": False,
    }


def check_full_gate(
    manifest_path: Path = DEFAULT_MANIFEST,
    start: str = GROWTH_START,
    end: str = GROWTH_END,
) -> list[dict[str, str]]:
    return check_growth_full_gate_v2(manifest_path, start, end)


def _evidence_blockers(output_root: Path) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for path_key, sha_key, code in (
        ("candidate", "candidate_sha256", "CANDIDATE_SHA256_MISMATCH"),
        ("manual_audit", "manual_audit_sha256", "MANUAL_AUDIT_SHA256_MISMATCH"),
        ("source_map", "source_map_sha256", "SOURCE_MAP_SHA256_MISMATCH"),
    ):
        path = output_root / GROWTH_FORMAL_INPUT[path_key]
        actual = _sha256(path)
        expected = GROWTH_FORMAL_INPUT[sha_key]
        if actual != expected:
            blockers.append({"code": code, "detail": f"{path_key} expected {expected}, observed {actual}"})
    return blockers


def _write_audit(
    output_root: Path,
    document: dict[str, Any],
    validation: dict[str, Any],
    *,
    curated: Path,
    wrote_curated: bool,
) -> Path:
    name = "w1_growth_output_full.json" if wrote_curated else "w1_growth_output_full_candidate.json"
    path = output_root / "audits" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "audit": document["audit"],
        "validation": validation,
        "candidate": {
            "path": str(output_root / GROWTH_FORMAL_INPUT["candidate"]),
            "sha256": GROWTH_FORMAL_INPUT["candidate_sha256"],
            "rows": validation["rows"],
            "pit_a_rows": validation["pit_a_rows"],
            "pit_c_rows": validation["pit_c_rows"],
            "curated_path": str(curated),
            "curated_written": wrote_curated,
            "research_ready": False,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_full(
    output_root: Path,
    start: str,
    end: str,
    mode: str,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    authorize_execute: bool = False,
) -> dict[str, Any]:
    if mode not in {"audit-only", "execute"}:
        raise ValueError(f"unsupported mode: {mode}")
    gate_blockers = check_full_gate(manifest_path, start, end)
    if gate_blockers:
        return _blocked(output_root, gate_blockers)
    if mode == "execute" and not authorize_execute:
        return _blocked(output_root, [{"code": "EXECUTE_NOT_AUTHORIZED", "detail": "execute requires explicit formal-write authorization"}])
    evidence_blockers = _evidence_blockers(output_root)
    if evidence_blockers:
        return _blocked(output_root, evidence_blockers)

    candidate = output_root / GROWTH_FORMAL_INPUT["candidate"]
    manual_audit = output_root / GROWTH_FORMAL_INPUT["manual_audit"]
    source_map = output_root / GROWTH_FORMAL_INPUT["source_map"]
    validation = validate_manual_candidate(candidate, manual_audit, source_map)
    if not validation["passed"]:
        return _blocked(output_root, [{"code": "MANUAL_CANDIDATE_VALIDATION_FAILED", "detail": ", ".join(validation["failures"])}])
    document = json.loads(manual_audit.read_text(encoding="utf-8"))
    frame = pd.read_parquet(candidate)
    curated = output_root / GROWTH_FORMAL_INPUT["formal_curated"]
    before = _sha256(curated)
    wrote_curated = False
    if mode == "execute":
        write_canonical_v2_snapshot(frame, curated)
        wrote_curated = True
    audit_path = _write_audit(output_root, document, validation, curated=curated, wrote_curated=wrote_curated)
    after = _sha256(curated)
    return {
        "audit": document["audit"],
        "validation": validation,
        "output": str(audit_path),
        "blocked": False,
        "research_ready": False,
        "curated_write": {
            "performed": wrote_curated,
            "path": str(curated),
            "sha256_before": before,
            "sha256_after": after,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit-only", "execute"), default="audit-only")
    parser.add_argument("--start", default=GROWTH_START)
    parser.add_argument("--end", default=GROWTH_END)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--authorize-formal-write", action="store_true")
    args = parser.parse_args()
    result = run_full(
        args.output_root,
        args.start,
        args.end,
        args.mode,
        manifest_path=args.manifest,
        authorize_execute=args.authorize_formal_write,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(2 if result.get("blocked") else 0)


if __name__ == "__main__":
    main()
