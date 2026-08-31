import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from scripts.data_lake.validate_macro_w1_global_financial_conditions_us_full_candidate import (
    AUDIT,
    CANDIDATE,
    HASHES,
    RAW_MANIFEST,
    STATE,
    validate_global_financial_conditions_us_full_candidate,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, str]]:
    candidate = tmp_path / "candidate.parquet"
    audit = tmp_path / "audit.json"
    state = tmp_path / "state"
    raw_manifest = tmp_path / "raw_manifest.json"
    state.mkdir()
    shutil.copy2(CANDIDATE, candidate)
    shutil.copy2(AUDIT, audit)
    shutil.copy2(RAW_MANIFEST, raw_manifest)
    for name in ("expected.json", "source_map.json", "manual_audit.json", "request_evidence_log.json"):
        shutil.copy2(STATE / name, state / name)
    hashes = dict(HASHES)
    hashes.update({"candidate_parquet": _sha(candidate), "candidate_audit": _sha(audit), "raw_manifest.json": _sha(raw_manifest)})
    return candidate, audit, state, raw_manifest, hashes


def test_us_full_candidate_passes() -> None:
    result = validate_global_financial_conditions_us_full_candidate()
    assert result["passed"], result
    assert result["candidate_rows"] == 47276
    assert len(result["series_full_gates"]) == 7


def test_us_full_candidate_rejects_wrong_frozen_sha() -> None:
    hashes = dict(HASHES)
    hashes["candidate_parquet"] = "0" * 64
    result = validate_global_financial_conditions_us_full_candidate(hashes=hashes)
    assert not result["passed"]
    assert "frozen_hashes_exact" in result["failures"]


@pytest.mark.parametrize("mutation", ["omission", "release_lag", "sunday", "pit", "formal"])
def test_us_full_candidate_audit_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    candidate, audit_path, state, raw_manifest, hashes = _fixture(tmp_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if mutation == "omission":
        audit["series_profiles"]["US.TREASURY.3M"]["structural_omissions"] = []
    elif mutation == "release_lag":
        audit["publication_lag_pending_series"] = []
    elif mutation == "sunday":
        audit["official_calendar_exceptions"]["US.EFFR"] = []
    elif mutation == "pit":
        audit["pit_counts"] = {"PIT-A": 47276, "PIT-C": 0}
    else:
        audit["formal_execution_allowed"] = True
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    hashes["candidate_audit"] = _sha(audit_path)
    result = validate_global_financial_conditions_us_full_candidate(candidate, audit_path, state, raw_manifest, hashes)
    assert not result["passed"], mutation


def test_us_full_candidate_rejects_naive_weekday_drop(tmp_path: Path) -> None:
    candidate, audit, state, raw_manifest, hashes = _fixture(tmp_path)
    frame = pd.read_parquet(candidate)
    frame = frame[~((frame["series_id"] == "US.EFFR") & (frame["reference_period"] == "2003-07-20"))]
    frame.to_parquet(candidate, index=False)
    hashes["candidate_parquet"] = _sha(candidate)
    result = validate_global_financial_conditions_us_full_candidate(candidate, audit, state, raw_manifest, hashes)
    assert not result["passed"]
