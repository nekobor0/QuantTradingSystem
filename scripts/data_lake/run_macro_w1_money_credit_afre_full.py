"""Series-level formal runner for the frozen AFRE RMB-loans history."""

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
from quant_trading_system.research.macro_data.w1_execution import build_audit, validate_audit  # noqa: E402
from scripts.data_lake.validate_macro_w1_full_entry import (  # noqa: E402
    MONEY_AFRE_END,
    MONEY_AFRE_FORMAL_INPUT,
    MONEY_AFRE_SERIES_ID,
    MONEY_AFRE_START,
    check_money_afre_full_gate_v2,
)
from scripts.data_lake.validate_macro_w1_money_credit_afre_full_candidate import validate_candidate  # noqa: E402


DEFAULT_MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"
CURATED_NAME = Path(MONEY_AFRE_FORMAL_INPUT["formal_curated"]).name


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _blocked(output_root: Path, blockers: list[dict[str, str]]) -> dict[str, Any]:
    curated = output_root / MONEY_AFRE_FORMAL_INPUT["formal_curated"]
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
    start: str = MONEY_AFRE_START,
    end: str = MONEY_AFRE_END,
) -> list[dict[str, str]]:
    return check_money_afre_full_gate_v2(manifest_path, start, end)


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

    candidate = output_root / MONEY_AFRE_FORMAL_INPUT["candidate"]
    candidate_audit = output_root / MONEY_AFRE_FORMAL_INPUT["candidate_audit"]
    if _sha256(candidate) != MONEY_AFRE_FORMAL_INPUT["candidate_sha256"]:
        return _blocked(output_root, [{"code": "CANDIDATE_SHA256_MISMATCH", "detail": str(candidate)}])
    if _sha256(candidate_audit) != MONEY_AFRE_FORMAL_INPUT["candidate_audit_sha256"]:
        return _blocked(output_root, [{"code": "CANDIDATE_AUDIT_SHA256_MISMATCH", "detail": str(candidate_audit)}])
    validation = validate_candidate(candidate, candidate_audit, root=output_root.parents[1])
    if not validation["passed"]:
        return _blocked(output_root, [{"code": "CANDIDATE_VALIDATION_FAILED", "detail": ", ".join(validation["failures"])}])

    frame = pd.read_parquet(candidate)
    observed = frame["reference_period"].astype(str).tolist()
    expected = []
    year, month = 2002, 1
    while (year, month) <= (2026, 7):
        expected.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    audit = build_audit(
        package_id="money_credit",
        run_mode="full",
        start=start,
        end=end,
        expected=expected,
        observed=observed,
        sources=[{"source_id": "PBOC_STATS", "series_id": MONEY_AFRE_SERIES_ID}],
        blockers=[],
        structural_omissions=[{"reference_period": "2025-12", "reason": "official direct monthly observation not found in the recorded PBOC publication scope; no cumulative differencing"}],
    )
    audit_validation = validate_audit(audit)
    curated = output_root / MONEY_AFRE_FORMAL_INPUT["formal_curated"]
    before = _sha256(curated)
    wrote_curated = False
    if mode == "execute":
        write_canonical_v2_snapshot(frame, curated)
        wrote_curated = True
    audit_name = "w1_money_credit_afre_full.json" if wrote_curated else "w1_money_credit_afre_formal_audit_only.json"
    audit_path = output_root / "audits" / audit_name
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "audit": audit,
                "validation": audit_validation,
                "candidate_validation": validation,
                "candidate": {
                    "path": str(candidate),
                    "sha256": MONEY_AFRE_FORMAL_INPUT["candidate_sha256"],
                    "rows": 294,
                    "calendar_rows": 295,
                    "structural_omissions": ["2025-12"],
                    "curated_path": str(curated),
                    "curated_written": wrote_curated,
                    "research_ready": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    after = _sha256(curated)
    return {
        "audit": audit,
        "validation": validation,
        "output": str(audit_path),
        "blocked": False,
        "research_ready": False,
        "curated_write": {"performed": wrote_curated, "path": str(curated), "sha256_before": before, "sha256_after": after},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit-only", "execute"), default="audit-only")
    parser.add_argument("--start", default=MONEY_AFRE_START)
    parser.add_argument("--end", default=MONEY_AFRE_END)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--authorize-formal-write", action="store_true")
    args = parser.parse_args()
    result = run_full(args.output_root, args.start, args.end, args.mode, manifest_path=args.manifest, authorize_execute=args.authorize_formal_write)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(2 if result.get("blocked") else 0)


if __name__ == "__main__":
    main()
