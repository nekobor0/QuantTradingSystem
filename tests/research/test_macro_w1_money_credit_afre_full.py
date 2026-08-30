from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

from scripts.data_lake.run_macro_w1_money_credit_afre_full import run_full
from scripts.data_lake.validate_macro_w1_full_entry import (
    MONEY_AFRE_END,
    MONEY_AFRE_FORMAL_INPUT,
    MONEY_AFRE_SERIES_GATE,
    MONEY_AFRE_SERIES_ID,
    MONEY_AFRE_START,
    check_money_afre_full_gate_v2,
)
from scripts.data_lake.validate_macro_w1_money_credit_afre_full_candidate import validate_candidate


ROOT = Path(__file__).resolve().parents[2]
REAL_LAKE = ROOT / "artifacts" / "macro_r011"


def _manifest(path: Path) -> Path:
    package = {
        "package_id": "money_credit",
        "gold_state": "GOLD_READY_ACTIVE_6_OF_6",
        "full_history_allowed": False,
        "full_blockers": ["legacy series blocker"],
        "series_full_gates": {MONEY_AFRE_SERIES_ID: MONEY_AFRE_SERIES_GATE},
    }
    path.write_text(json.dumps({"schema_version": 2, "gate_version": 2, "packages": [package]}), encoding="utf-8")
    return path


def _authorized_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    lake = repo / "artifacts" / "macro_r011"
    for key in ("candidate", "candidate_audit"):
        source = REAL_LAKE / MONEY_AFRE_FORMAL_INPUT[key]
        target = lake / MONEY_AFRE_FORMAL_INPUT[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    audit = json.loads((REAL_LAKE / MONEY_AFRE_FORMAL_INPUT["candidate_audit"]).read_text(encoding="utf-8"))
    row_hashes = set(pd.read_parquet(REAL_LAKE / MONEY_AFRE_FORMAL_INPUT["candidate"])["raw_sha256"])
    for item in audit["raw_closure"]["files"]:
        if item.get("sha256") not in row_hashes:
            continue
        source = ROOT / item["path"]
        target = repo / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return lake, _manifest(tmp_path / "manifest.json"), repo


def test_real_294_row_candidate_is_canonical_and_structural_gap_is_exact() -> None:
    result = validate_candidate(
        REAL_LAKE / MONEY_AFRE_FORMAL_INPUT["candidate"],
        REAL_LAKE / MONEY_AFRE_FORMAL_INPUT["candidate_audit"],
    )
    assert result["passed"], result
    assert result["rows"] == 294
    assert result["calendar_rows"] == 295
    assert result["structural_omissions"] == ["2025-12"]
    assert result["pit_a_rows"] == 7
    assert result["pit_c_rows"] == 287


def test_audit_only_never_writes_or_changes_curated(tmp_path: Path) -> None:
    lake, manifest, _ = _authorized_fixture(tmp_path)
    curated = lake / MONEY_AFRE_FORMAL_INPUT["formal_curated"]
    curated.parent.mkdir(parents=True)
    curated.write_bytes(b"sentinel")
    before = hashlib.sha256(curated.read_bytes()).hexdigest()
    result = run_full(lake, MONEY_AFRE_START, MONEY_AFRE_END, "audit-only", manifest_path=manifest)
    assert result["blocked"] is False
    assert result["validation"]["passed"] is True
    assert result["curated_write"]["performed"] is False
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == before
    assert Path(result["output"]).name == "w1_money_credit_afre_formal_audit_only.json"


def test_synthetic_authorized_execute_is_deterministic(tmp_path: Path) -> None:
    lake, manifest, _ = _authorized_fixture(tmp_path)
    first = run_full(lake, MONEY_AFRE_START, MONEY_AFRE_END, "execute", manifest_path=manifest, authorize_execute=True)
    assert first["blocked"] is False
    assert first["research_ready"] is False
    curated = lake / MONEY_AFRE_FORMAL_INPUT["formal_curated"]
    frame = pd.read_parquet(curated)
    assert len(frame) == 294
    assert "2025-12" not in set(frame["reference_period"])
    first_hash = hashlib.sha256(curated.read_bytes()).hexdigest()
    second = run_full(lake, MONEY_AFRE_START, MONEY_AFRE_END, "execute", manifest_path=manifest, authorize_execute=True)
    assert second["blocked"] is False
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == first_hash


def test_execute_requires_explicit_authorization(tmp_path: Path) -> None:
    lake, manifest, _ = _authorized_fixture(tmp_path)
    result = run_full(lake, MONEY_AFRE_START, MONEY_AFRE_END, "execute", manifest_path=manifest)
    assert result["blocked"] is True
    assert result["blockers"][0]["code"] == "EXECUTE_NOT_AUTHORIZED"
    assert not (lake / MONEY_AFRE_FORMAL_INPUT["formal_curated"]).exists()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("window", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("scope", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("omission", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("rows", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("target", "FORMAL_TARGET_MISMATCH"),
        ("candidate_hash", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("audit_hash", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("series_allowed", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("formal_written", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("research_ready", "MONEY_AFRE_SERIES_GATE_MISMATCH"),
        ("package_allowed", "MONEY_PACKAGE_GATE_MUST_REMAIN_BLOCKED"),
    ],
)
def test_gate_rejects_contract_mutations(tmp_path: Path, mutation: str, code: str) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    package = document["packages"][0]
    gate = package["series_full_gates"][MONEY_AFRE_SERIES_ID]
    if mutation == "window":
        gate["full_window"]["start"] = "2002-02"
    elif mutation == "scope":
        gate["full_window"]["scope"] = "all_months"
    elif mutation == "omission":
        gate["full_window"]["structural_omissions"] = []
    elif mutation == "rows":
        gate["full_window"]["observed_rows"] = 295
    elif mutation == "target":
        gate["formal_input"]["formal_curated"] = "curated/tampered.parquet"
    elif mutation == "candidate_hash":
        gate["formal_input"]["candidate_sha256"] = "0" * 64
    elif mutation == "audit_hash":
        gate["formal_input"]["candidate_audit_sha256"] = "0" * 64
    elif mutation == "series_allowed":
        gate["full_history_allowed"] = False
    elif mutation == "formal_written":
        gate["formal_curated_written"] = False
    elif mutation == "research_ready":
        gate["research_ready"] = True
    else:
        package["full_history_allowed"] = True
    manifest.write_text(json.dumps(document), encoding="utf-8")
    assert check_money_afre_full_gate_v2(manifest)[0]["code"] == code


def test_gate_rejects_non_exact_requested_window(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    assert check_money_afre_full_gate_v2(manifest, "2002-02", MONEY_AFRE_END)[0]["code"] == "FULL_WINDOW_OUT_OF_RANGE"


@pytest.mark.parametrize(("key", "code"), [("candidate", "CANDIDATE_SHA256_MISMATCH"), ("candidate_audit", "CANDIDATE_AUDIT_SHA256_MISMATCH")])
def test_evidence_hash_mutation_fails_closed(tmp_path: Path, key: str, code: str) -> None:
    lake, manifest, _ = _authorized_fixture(tmp_path)
    target = lake / MONEY_AFRE_FORMAL_INPUT[key]
    target.write_bytes(target.read_bytes() + b"tamper")
    result = run_full(lake, MONEY_AFRE_START, MONEY_AFRE_END, "audit-only", manifest_path=manifest)
    assert result["blocked"] is True
    assert result["blockers"][0]["code"] == code
    assert not (lake / MONEY_AFRE_FORMAL_INPUT["formal_curated"]).exists()


def test_raw_hash_mutation_fails_closed(tmp_path: Path) -> None:
    lake, manifest, repo = _authorized_fixture(tmp_path)
    audit = json.loads((lake / MONEY_AFRE_FORMAL_INPUT["candidate_audit"]).read_text(encoding="utf-8"))
    row_hashes = set(pd.read_parquet(lake / MONEY_AFRE_FORMAL_INPUT["candidate"])["raw_sha256"])
    raw = next(repo / item["path"] for item in audit["raw_closure"]["files"] if item.get("sha256") in row_hashes)
    raw.write_bytes(raw.read_bytes() + b"tamper")
    result = run_full(lake, MONEY_AFRE_START, MONEY_AFRE_END, "audit-only", manifest_path=manifest)
    assert result["blocked"] is True
    assert result["blockers"][0]["code"] == "CANDIDATE_VALIDATION_FAILED"
    assert "raw_files_hash_match" in result["blockers"][0]["detail"]
    assert not (lake / MONEY_AFRE_FORMAL_INPUT["formal_curated"]).exists()


@pytest.mark.parametrize("authorized", [False, True])
def test_unified_runner_dispatches_only_the_authorized_afre_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authorized: bool) -> None:
    from scripts.data_lake import run_macro_w1_package as unified

    observed: dict[str, object] = {}

    def fake_gate(*args: object, **kwargs: object) -> list[dict[str, str]]:
        return []

    def fake_run(output_root: Path, start: str, end: str, mode: str, *, authorize_execute: bool = False) -> dict[str, object]:
        observed.update(output_root=output_root, start=start, end=end, mode=mode, authorize_execute=authorize_execute)
        return {"blocked": not authorize_execute, "research_ready": False}

    monkeypatch.setattr(unified, "check_money_afre_full_gate", fake_gate)
    monkeypatch.setattr(unified, "run_money_afre_full", fake_run)
    argv = [
        "run_macro_w1_package.py", "--package", "money_credit", "--series", MONEY_AFRE_SERIES_ID,
        "--mode", "full", "--start", MONEY_AFRE_START, "--end", MONEY_AFRE_END,
        "--output-root", str(tmp_path / "lake"),
    ]
    if authorized:
        argv.append("--authorize-formal-write")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        unified.main()
    assert exc.value.code == (0 if authorized else 2)
    assert observed["authorize_execute"] is authorized
