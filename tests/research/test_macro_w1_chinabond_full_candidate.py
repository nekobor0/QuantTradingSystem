from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from scripts.data_lake.validate_macro_w1_chinabond_full_candidate import (
    CANDIDATE_ROOT,
    FROZEN_HASHES,
    validate_chinabond_full_candidate,
)


ROOT = Path(__file__).resolve().parents[2]


def _copy_candidate(tmp_path: Path) -> Path:
    target = tmp_path / "candidate"
    shutil.copytree(CANDIDATE_ROOT, target)
    return target


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rehash(candidate_root: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((candidate_root / name).read_bytes()).hexdigest().upper()
        for name in FROZEN_HASHES
    }


def test_chinabond_full_candidate_accepts_frozen_12318_row_evidence() -> None:
    result = validate_chinabond_full_candidate()
    assert result["passed"], result
    assert result["candidate_rows"] == 12318
    assert result["candidate_qualified_series"] == [
        "CN.CHINABOND.GOV.YTM.10Y",
        "CN.CHINABOND.GOV.YTM.1Y",
    ]
    assert result["pit_grade"] == "C"


@pytest.mark.parametrize("name", sorted(FROZEN_HASHES))
def test_chinabond_candidate_rejects_any_wrong_frozen_sha(name: str) -> None:
    hashes = dict(FROZEN_HASHES)
    hashes[name] = "0" * 64
    result = validate_chinabond_full_candidate(frozen_hashes=hashes)
    assert not result["passed"]
    assert "frozen_hashes_exact" in result["failures"]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("window", "requested_window_exact"),
        ("row_count", "parquet_matches_expected"),
        ("control", "expected_profile_exact"),
        ("full_history", "no_premature_state"),
        ("manual_audit", "manual_audit_exact"),
    ],
)
def test_chinabond_candidate_rejects_metadata_mutations(tmp_path: Path, mutation: str, failure: str) -> None:
    candidate_root = _copy_candidate(tmp_path)
    if mutation == "manual_audit":
        path = candidate_root / "manual_audit.json"
        value = _load(path)
        value["failures"] = ["tampered"]
    else:
        path = candidate_root / "expected.json"
        value = _load(path)
        if mutation == "window":
            value["requested_window"]["start"] = "2002-01-05"
        elif mutation == "row_count":
            value["rows"].pop()
        elif mutation == "control":
            value["control_values"]["2026-08-24"]["CN.CHINABOND.GOV.YTM.1Y"] = 9.99
        else:
            value["full_history_allowed"] = True
    _write(path, value)
    result = validate_chinabond_full_candidate(candidate_root, frozen_hashes=_rehash(candidate_root))
    assert not result["passed"]
    assert failure in result["failures"]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("value", "control_values_exact"),
        ("series", "series_and_date_sets_exact"),
        ("pit", "pit_c_exact"),
        ("duplicate", "unique_primary_keys"),
    ],
)
def test_chinabond_candidate_rejects_row_mutations(tmp_path: Path, mutation: str, failure: str) -> None:
    candidate_root = _copy_candidate(tmp_path)
    path = candidate_root / "chinabond_ytm_full_candidate.parquet"
    frame = pd.read_parquet(path)
    if mutation == "value":
        index = frame.index[(frame["series_id"] == "CN.CHINABOND.GOV.YTM.1Y") & (frame["reference_period"] == "2026-08-24")][0]
        frame.loc[index, "value"] = 9.99
    elif mutation == "series":
        frame.loc[0, "series_id"] = "CN.REPO.DR007"
    elif mutation == "pit":
        frame.loc[0, "pit_grade"] = "A"
    else:
        frame.loc[1, ["series_id", "reference_period", "vintage_id"]] = frame.loc[0, ["series_id", "reference_period", "vintage_id"]].values
    frame.to_parquet(path, index=False)
    result = validate_chinabond_full_candidate(candidate_root, frozen_hashes=_rehash(candidate_root))
    assert not result["passed"]
    assert failure in result["failures"]


def test_chinabond_candidate_rejects_raw_tamper(tmp_path: Path) -> None:
    candidate_root = _copy_candidate(tmp_path)
    source_map = _load(candidate_root / "source_map.json")
    repo_root = tmp_path / "repo"
    for item in source_map["raw_closure"]:
        source = ROOT / item["raw_path"]
        target = repo_root / item["raw_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    target.write_bytes(target.read_bytes() + b"tamper")
    result = validate_chinabond_full_candidate(
        candidate_root,
        repo_root=repo_root,
        frozen_hashes=_rehash(candidate_root),
    )
    assert not result["passed"]
    assert "raw_closure_exact" in result["failures"]
