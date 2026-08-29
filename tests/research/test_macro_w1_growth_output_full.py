from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

from scripts.data_lake.run_macro_w1_growth_output_full import CURATED_NAME, run_full
from scripts.data_lake.validate_macro_w1_full_entry import (
    GROWTH_END,
    GROWTH_FORMAL_INPUT,
    GROWTH_SCOPE,
    GROWTH_SERIES_WINDOWS,
    GROWTH_START,
    check_growth_full_gate_v2,
)


ROOT = Path(__file__).resolve().parents[2]
REAL_LAKE = ROOT / "artifacts" / "macro_r011"


def _manifest(path: Path, *, allowed: bool = True) -> Path:
    package = {
        "package_id": "growth_output",
        "full_history_allowed": allowed,
        "full_blockers": [] if allowed else ["synthetic closed gate"],
        "full_window": {
            "start": GROWTH_START,
            "end": GROWTH_END,
            "scope": GROWTH_SCOPE,
            "series_windows": GROWTH_SERIES_WINDOWS,
        },
        "formal_input": GROWTH_FORMAL_INPUT,
    }
    path.write_text(json.dumps({"schema_version": 2, "gate_version": 2, "packages": [package]}), encoding="utf-8")
    return path


def _authorized_fixture(tmp_path: Path) -> tuple[Path, Path]:
    lake = tmp_path / "synthetic_authorized_lake"
    for key in ("candidate", "manual_audit", "source_map"):
        source = REAL_LAKE / GROWTH_FORMAL_INPUT[key]
        target = lake / GROWTH_FORMAL_INPUT[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return lake, _manifest(tmp_path / "authorized_manifest.json")


def test_audit_only_validates_581_rows_and_never_writes_curated(tmp_path: Path) -> None:
    lake, manifest = _authorized_fixture(tmp_path)
    curated = lake / GROWTH_FORMAL_INPUT["formal_curated"]
    curated.parent.mkdir(parents=True)
    curated.write_bytes(b"audit-only-sentinel")
    before = hashlib.sha256(curated.read_bytes()).hexdigest()
    result = run_full(lake, GROWTH_START, GROWTH_END, "audit-only", manifest_path=manifest)
    assert result["blocked"] is False
    assert result["validation"]["passed"] is True
    assert result["validation"]["rows"] == 581
    assert result["validation"]["pit_a_rows"] == 38
    assert result["validation"]["pit_c_rows"] == 543
    assert result["curated_write"]["performed"] is False
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == before
    assert Path(result["output"]).name == "w1_growth_output_full_candidate.json"


def test_synthetic_authorized_execute_is_deterministic_and_research_not_ready(tmp_path: Path) -> None:
    lake, manifest = _authorized_fixture(tmp_path)
    first = run_full(lake, GROWTH_START, GROWTH_END, "execute", manifest_path=manifest, authorize_execute=True)
    curated = lake / "curated" / CURATED_NAME
    assert first["blocked"] is False
    assert first["curated_write"]["performed"] is True
    assert first["research_ready"] is False
    assert first["audit"]["research_ready"] is False
    assert Path(first["output"]).name == "w1_growth_output_full.json"
    frame = pd.read_parquet(curated)
    assert len(frame) == 581
    assert frame.groupby("series_id").size().to_dict() == {
        "CN.GDP.NOMINAL.YTD": 138,
        "CN.GDP.REAL.YOY": 134,
        "CN.INDUSTRIAL.VA.YOY": 309,
    }
    first_hash = hashlib.sha256(curated.read_bytes()).hexdigest()
    second = run_full(lake, GROWTH_START, GROWTH_END, "execute", manifest_path=manifest, authorize_execute=True)
    assert second["blocked"] is False
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == first_hash


def test_execute_without_explicit_authorization_is_rejected_and_preserves_target(tmp_path: Path) -> None:
    lake, manifest = _authorized_fixture(tmp_path)
    curated = lake / GROWTH_FORMAL_INPUT["formal_curated"]
    curated.parent.mkdir(parents=True)
    curated.write_bytes(b"sentinel")
    before = hashlib.sha256(curated.read_bytes()).hexdigest()
    result = run_full(lake, GROWTH_START, GROWTH_END, "execute", manifest_path=manifest)
    assert result["blockers"][0]["code"] == "EXECUTE_NOT_AUTHORIZED"
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("scope", "FULL_SCOPE_MISMATCH"),
        ("series_windows", "FULL_SERIES_WINDOWS_MISMATCH"),
        ("target", "FORMAL_TARGET_MISMATCH"),
    ],
)
def test_gate_rejects_wrong_scope_series_windows_and_formal_target(tmp_path: Path, mutation: str, code: str) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    package = document["packages"][0]
    if mutation == "scope":
        package["full_window"]["scope"] = "retrospective_only"
    elif mutation == "series_windows":
        package["full_window"]["series_windows"]["CN.GDP.REAL.YOY"]["start"] = "1992-Q1"
    else:
        package["formal_input"]["formal_curated"] = "curated/tampered.parquet"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    assert check_growth_full_gate_v2(manifest)[0]["code"] == code


def test_gate_rejects_non_exact_requested_window(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    assert check_growth_full_gate_v2(manifest, "1993-01", GROWTH_END)[0]["code"] == "FULL_WINDOW_OUT_OF_RANGE"


def test_candidate_sha_mismatch_fails_closed(tmp_path: Path) -> None:
    lake, manifest = _authorized_fixture(tmp_path)
    candidate = lake / GROWTH_FORMAL_INPUT["candidate"]
    candidate.write_bytes(candidate.read_bytes() + b"tamper")
    result = run_full(lake, GROWTH_START, GROWTH_END, "audit-only", manifest_path=manifest)
    assert result["blockers"][0]["code"] == "CANDIDATE_SHA256_MISMATCH"
    assert not (lake / GROWTH_FORMAL_INPUT["formal_curated"]).exists()


def test_damaged_manual_audit_fails_closed(tmp_path: Path) -> None:
    lake, manifest = _authorized_fixture(tmp_path)
    (lake / GROWTH_FORMAL_INPUT["manual_audit"]).write_text("{}", encoding="utf-8")
    result = run_full(lake, GROWTH_START, GROWTH_END, "audit-only", manifest_path=manifest)
    assert result["blockers"][0]["code"] == "MANUAL_AUDIT_SHA256_MISMATCH"
    assert not (lake / GROWTH_FORMAL_INPUT["formal_curated"]).exists()


def test_real_gate_is_open_for_the_frozen_formal_contract() -> None:
    assert check_growth_full_gate_v2(ROOT / "config" / "macro_w1_execution_manifest.json") == []
    assert GROWTH_FORMAL_INPUT["formal_curated"] == f"curated/{CURATED_NAME}"


@pytest.mark.parametrize("authorized", [False, True])
def test_unified_package_runner_dispatches_growth_with_explicit_authorization_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authorized: bool,
) -> None:
    from scripts.data_lake import run_macro_w1_package as unified

    observed: dict[str, object] = {}

    def fake_run(output_root: Path, start: str, end: str, mode: str, *, authorize_execute: bool = False) -> dict[str, object]:
        observed.update(output_root=output_root, start=start, end=end, mode=mode, authorize_execute=authorize_execute)
        return {"blocked": not authorize_execute, "research_ready": False}

    monkeypatch.setattr(unified, "run_growth_full", fake_run)
    argv = [
        "run_macro_w1_package.py",
        "--package",
        "growth_output",
        "--mode",
        "full",
        "--start",
        GROWTH_START,
        "--end",
        GROWTH_END,
        "--output-root",
        str(tmp_path / "lake"),
    ]
    if authorized:
        argv.append("--authorize-formal-write")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        unified.main()
    assert exc.value.code == (0 if authorized else 2)
    assert observed == {
        "output_root": tmp_path / "lake",
        "start": GROWTH_START,
        "end": GROWTH_END,
        "mode": "execute",
        "authorize_execute": authorized,
    }
