"""Gate-protected NBS prices PIT-A candidate writer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import write_canonical_v2_snapshot  # noqa: E402
from quant_trading_system.research.macro_data.w1_prices_history import run_full_candidate  # noqa: E402
from scripts.data_lake.validate_macro_w1_full_entry import check_full_gate_v2  # noqa: E402


CURATED_NAME = "w1_prices_official_release_pit_a.parquet"
PIT_A_START = "2021-01"
PIT_A_END = "2026-07"
REQUIRED_SCOPE = "pit_a_official_release"
DEFAULT_MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_full_gate(manifest_path: Path, start: str, end: str) -> list[dict[str, str]]:
    return check_full_gate_v2(
        manifest_path,
        "prices",
        PIT_A_START,
        PIT_A_END,
        REQUIRED_SCOPE,
        start,
        end,
    )


def _write_candidate_audit(output_root: Path, result: dict[str, Any], *, curated: Path, wrote_curated: bool) -> Path:
    audit_name = "w1_prices_full.json" if wrote_curated else "w1_prices_full_candidate.json"
    audit_path = output_root / "audits" / audit_name
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    source = result["audit"]["sources"][0]
    payload = {
        "audit": result["audit"],
        "validation": result["validation"],
        "candidate": {
            "rows": result.get("candidate_rows", source["successful_parse"]["rows"]),
            "curated_path": str(curated),
            "curated_written": wrote_curated,
            "pit_grade": source["pit_grade"],
            "research_ready": False,
        },
    }
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return audit_path


def run_full(
    output_root: Path,
    start: str,
    end: str,
    mode: str,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    if mode not in {"audit-only", "execute"}:
        raise ValueError(f"unsupported mode: {mode}")
    curated = output_root / "curated" / CURATED_NAME
    before = _sha256(curated)
    if mode == "execute":
        blockers = check_full_gate(manifest_path, start, end)
        if blockers:
            return {
                "blocked": True,
                "blockers": blockers,
                "curated_path": str(curated),
                "curated_exists": curated.exists(),
                "curated_sha256_before": before,
                "curated_sha256_after": _sha256(curated),
                "research_ready": False,
            }
    result = run_full_candidate(output_root, start, end)
    frame = result.pop("_frame")
    wrote_curated = False
    if mode == "execute" and result["validation"]["passed"] and not result["audit"]["blocked"]:
        write_canonical_v2_snapshot(frame, curated)
        wrote_curated = True
    audit_path = _write_candidate_audit(output_root, result, curated=curated, wrote_curated=wrote_curated)
    result["output"] = str(audit_path)
    result["candidate_rows"] = len(frame)
    result["curated_write"] = {
        "performed": wrote_curated,
        "path": str(curated),
        "sha256_before": before,
        "sha256_after": _sha256(curated),
    }
    result["blocked"] = bool(result["audit"]["blocked"])
    result["research_ready"] = False
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit-only", "execute"), default="audit-only")
    parser.add_argument("--start", default=PIT_A_START)
    parser.add_argument("--end", default=PIT_A_END)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    args = parser.parse_args()
    result = run_full(args.output_root, args.start, args.end, args.mode, manifest_path=args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.mode == "execute" and result.get("blocked"):
        raise SystemExit(2)
    raise SystemExit(0 if result["validation"]["passed"] else 1)


if __name__ == "__main__":
    main()
