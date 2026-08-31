import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts.data_lake.validate_macro_w1_global_financial_conditions_fx_candidate import (
    AUDIT_PATH,
    FROZEN_HASHES,
    RAW_ROOT,
    STATE_ROOT,
    validate_global_financial_conditions_fx_candidate,
)


def _copy_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    state_root = tmp_path / "state"
    raw_root = tmp_path / "raw"
    shutil.copytree(STATE_ROOT, state_root)
    shutil.copytree(RAW_ROOT, raw_root)
    audit_path = tmp_path / "audit.json"
    shutil.copy2(AUDIT_PATH, audit_path)
    return state_root, audit_path, raw_root


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rehash(state_root: Path, audit_path: Path, raw_root: Path) -> dict[str, str]:
    paths = {
        "candidate_audit": audit_path,
        "source_map.json": state_root / "source_map.json",
        "manual_audit.json": state_root / "manual_audit.json",
        "request_evidence_log.json": state_root / "request_evidence_log.json",
        "raw_manifest.json": raw_root / "raw_manifest.json",
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest().upper() for name, path in paths.items()}


def test_fx_candidate_accepts_frozen_zero_row_blocked_evidence() -> None:
    result = validate_global_financial_conditions_fx_candidate()
    assert result["passed"], result
    assert result["candidate_rows"] == 0
    assert result["gold_ready_count"] == 7
    assert result["gold_missing"] == ["USD.CNY", "USD.CNH"]


@pytest.mark.parametrize("name", sorted(FROZEN_HASHES))
def test_fx_candidate_rejects_any_wrong_frozen_sha(name: str) -> None:
    hashes = dict(FROZEN_HASHES)
    hashes[name] = "0" * 64
    result = validate_global_financial_conditions_fx_candidate(frozen_hashes=hashes)
    assert not result["passed"]
    assert "frozen_hashes_exact" in result["failures"]


@pytest.mark.parametrize(
    ("target", "mutation", "failure"),
    [
        ("audit", "inject_row", "audit_zero_row_block_exact"),
        ("audit", "pass_cny", "audit_zero_row_block_exact"),
        ("audit", "allow_formal", "flags_fail_closed"),
        ("source", "accept_public_quote", "cny_diagnostics_rejected"),
        ("source", "resolve_cnh", "cnh_entitlement_blocked"),
        ("manual", "promote_pit", "manual_audit_fail_closed"),
        ("request", "exceed_budget", "request_budget_and_rejections_exact"),
        ("raw_manifest", "accept_raw", "diagnostic_raw_exact"),
    ],
)
def test_fx_candidate_rejects_rehashed_semantic_tamper(
    tmp_path: Path, target: str, mutation: str, failure: str
) -> None:
    state_root, audit_path, raw_root = _copy_evidence(tmp_path)
    paths = {
        "audit": audit_path,
        "source": state_root / "source_map.json",
        "manual": state_root / "manual_audit.json",
        "request": state_root / "request_evidence_log.json",
        "raw_manifest": raw_root / "raw_manifest.json",
    }
    path = paths[target]
    value = _load(path)
    if mutation == "inject_row":
        value["candidate_rows"] = 1
    elif mutation == "pass_cny":
        value["passed_series"] = ["USD.CNY"]
    elif mutation == "allow_formal":
        value["formal_execution_allowed"] = True
    elif mutation == "accept_public_quote":
        value["series"]["USD.CNY"]["diagnostic_sources"][0]["accepted"] = True
    elif mutation == "resolve_cnh":
        value["series"]["USD.CNH"]["status"] = "ready"
    elif mutation == "promote_pit":
        value["control_checks"]["pit_c_promoted_to_pit_a"] = True
        value["candidate_rows"] = 1
    elif mutation == "exceed_budget":
        value["request_budget"]["direct_http_attempts_recorded"] = 31
        value["request_budget"]["budget_exceeded"] = True
    else:
        value[0]["accepted"] = True
    _write(path, value)
    result = validate_global_financial_conditions_fx_candidate(
        state_root, audit_path, raw_root, _rehash(state_root, audit_path, raw_root)
    )
    assert not result["passed"]
    assert failure in result["failures"]


def test_fx_candidate_rejects_raw_content_tamper(tmp_path: Path) -> None:
    state_root, audit_path, raw_root = _copy_evidence(tmp_path)
    raw_file = next(path for path in raw_root.iterdir() if path.name != "raw_manifest.json")
    raw_file.write_bytes(raw_file.read_bytes() + b"tamper")
    result = validate_global_financial_conditions_fx_candidate(
        state_root, audit_path, raw_root, _rehash(state_root, audit_path, raw_root)
    )
    assert not result["passed"]
    assert "diagnostic_raw_exact" in result["failures"]
