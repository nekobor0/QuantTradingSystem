import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts.data_lake.validate_macro_w1_rates_gold_candidate import (
    AUDIT_PATH,
    CANDIDATE_ROOT,
    FROZEN_HASHES,
    validate_rates_gold_candidate,
)


def _copy_candidate(tmp_path: Path) -> tuple[Path, Path]:
    candidate_root = tmp_path / "candidate"
    shutil.copytree(CANDIDATE_ROOT, candidate_root)
    audit_path = tmp_path / "candidate_audit.json"
    shutil.copy2(AUDIT_PATH, audit_path)
    return candidate_root, audit_path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rehash(candidate_root: Path, audit_path: Path) -> dict[str, str]:
    paths = {
        "expected.json": candidate_root / "expected.json",
        "source_map.json": candidate_root / "source_map.json",
        "manual_audit.json": candidate_root / "manual_audit.json",
        "candidate_audit": audit_path,
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest().upper() for name, path in paths.items()}


def test_rates_gold_candidate_accepts_frozen_eleven_of_eleven_evidence():
    result = validate_rates_gold_candidate()
    assert result["passed"], result
    assert result["gold_ready_count"] == 11
    assert result["gold_required_count"] == 11
    assert result["gold_missing"] == []


@pytest.mark.parametrize("name", sorted(FROZEN_HASHES))
def test_rates_gold_candidate_rejects_any_wrong_frozen_sha(name: str):
    hashes = dict(FROZEN_HASHES)
    hashes[name] = "0" * 64
    result = validate_rates_gold_candidate(frozen_hashes=hashes)
    assert not result["passed"]
    assert "frozen_hashes_exact" in result["failures"]


@pytest.mark.parametrize("mutation", ["window", "row_count", "series_count"])
def test_rates_gold_candidate_rejects_wrong_profile(tmp_path: Path, mutation: str):
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / "expected.json"
    expected = _load(path)
    if mutation == "window":
        expected["requested_window"]["daily"][0] = "2026-08-23"
    elif mutation == "row_count":
        expected["rows"].pop()
    else:
        expected["rows"][0]["series_id"] = "CN.SHIBOR.ON"
    _write(path, expected)
    result = validate_rates_gold_candidate(candidate_root, audit_path, _rehash(candidate_root, audit_path))
    assert not result["passed"]


@pytest.mark.parametrize("series_id", ["CN.SHIBOR.1W", "CN.LPR.1Y"])
def test_rates_gold_candidate_rejects_value_or_tenor_mismatch(tmp_path: Path, series_id: str):
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / "expected.json"
    expected = _load(path)
    row = next(item for item in expected["rows"] if item["series_id"] == series_id)
    row["value"] += 0.1
    _write(path, expected)
    result = validate_rates_gold_candidate(candidate_root, audit_path, _rehash(candidate_root, audit_path))
    assert not result["passed"]
    failure = "shibor_values_match_raw" if series_id.startswith("CN.SHIBOR") else "lpr_values_and_times_match_raw"
    assert failure in result["failures"]


def test_rates_gold_candidate_rejects_lpr_time_mismatch(tmp_path: Path):
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / "expected.json"
    expected = _load(path)
    row = next(item for item in expected["rows"] if item["series_id"] == "CN.LPR.5Y_PLUS")
    row["release_at"] = "2026-07-20T09:01:00+08:00"
    _write(path, expected)
    result = validate_rates_gold_candidate(candidate_root, audit_path, _rehash(candidate_root, audit_path))
    assert not result["passed"]
    assert "lpr_values_and_times_match_raw" in result["failures"]


def test_rates_gold_candidate_rejects_blocked_series_row(tmp_path: Path):
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / "expected.json"
    expected = _load(path)
    expected["rows"][0]["series_id"] = "CN.REPO.DR007"
    _write(path, expected)
    result = validate_rates_gold_candidate(candidate_root, audit_path, _rehash(candidate_root, audit_path))
    assert not result["passed"]
    assert "blocked_series_have_no_rows" in result["failures"]


def test_rates_gold_candidate_rejects_manual_audit_damage(tmp_path: Path):
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / "manual_audit.json"
    manual = _load(path)
    manual["failures"] = ["tampered"]
    _write(path, manual)
    result = validate_rates_gold_candidate(candidate_root, audit_path, _rehash(candidate_root, audit_path))
    assert not result["passed"]
    assert "manual_audit_exact" in result["failures"]


def test_rates_gold_candidate_rejects_raw_tamper(tmp_path: Path):
    candidate_root, audit_path = _copy_candidate(tmp_path)
    raw = candidate_root / "raw" / "shibor_2026-01-01_2026-08-25.json"
    raw.write_bytes(raw.read_bytes() + b"\n")
    result = validate_rates_gold_candidate(candidate_root, audit_path, _rehash(candidate_root, audit_path))
    assert not result["passed"]
    assert "raw_hashes_match" in result["failures"]
