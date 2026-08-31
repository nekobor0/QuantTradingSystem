import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts.data_lake.validate_macro_w1_global_financial_conditions_us_candidate import (
    AUDIT_PATH,
    CANDIDATE_ROOT,
    FROZEN_HASHES,
    validate_global_financial_conditions_us_candidate,
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
        "candidate_canonical_v2.parquet": candidate_root / "candidate_canonical_v2.parquet",
        "expected.json": candidate_root / "expected.json",
        "source_map.json": candidate_root / "source_map.json",
        "manual_audit.json": candidate_root / "manual_audit.json",
        "raw_manifest.json": candidate_root / "raw_manifest.json",
        "candidate_audit": audit_path,
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest().upper() for name, path in paths.items()}


def test_global_us_candidate_accepts_frozen_seven_of_nine_pit_c_gold() -> None:
    result = validate_global_financial_conditions_us_candidate()
    assert result["passed"], result
    assert result["gold_ready_count"] == 7
    assert result["gold_required_count"] == 9
    assert result["gold_missing"] == ["USD.CNY", "USD.CNH"]
    assert result["pit_counts"] == {"PIT-A": 0, "PIT-C": 14}


@pytest.mark.parametrize("name", sorted(FROZEN_HASHES))
def test_global_us_candidate_rejects_any_wrong_frozen_sha(name: str) -> None:
    hashes = dict(FROZEN_HASHES)
    hashes[name] = "0" * 64
    result = validate_global_financial_conditions_us_candidate(frozen_hashes=hashes)
    assert not result["passed"]
    assert "frozen_hashes_exact" in result["failures"]


@pytest.mark.parametrize(
    ("file_name", "mutation", "failure"),
    [
        ("expected.json", "drop_row", "expected_and_parquet_keys_exact"),
        ("expected.json", "wrong_value", "values_fields_units_exact"),
        ("expected.json", "write_cny", "fx_series_have_no_rows"),
        ("expected.json", "allow_full", "expected_flags_fail_closed"),
        ("manual_audit.json", "pit_a", "manual_audit_exact"),
        ("raw_manifest.json", "wrong_raw_sha", "row_raw_sha_closure"),
    ],
)
def test_global_us_candidate_rejects_rehashed_semantic_tamper(
    tmp_path: Path, file_name: str, mutation: str, failure: str
) -> None:
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / file_name
    value = _load(path)
    if mutation == "drop_row":
        value["rows"].pop()
    elif mutation == "wrong_value":
        value["rows"][0]["value"] += 1.0
    elif mutation == "write_cny":
        value["blocked_series"] = ["USD.CNH"]
    elif mutation == "allow_full":
        value["full_history_allowed"] = True
    elif mutation == "pit_a":
        value["pit_counts"] = {"PIT-A": 1, "PIT-C": 13}
    else:
        next(iter(value.values()))["sha256"] = "0" * 64
    _write(path, value)
    result = validate_global_financial_conditions_us_candidate(
        candidate_root, audit_path, _rehash(candidate_root, audit_path)
    )
    assert not result["passed"]
    assert failure in result["failures"]


def test_global_us_candidate_rejects_broad_dollar_basis_or_subindex_tamper(tmp_path: Path) -> None:
    candidate_root, audit_path = _copy_candidate(tmp_path)
    path = candidate_root / "expected.json"
    expected = _load(path)
    for row in expected["rows"]:
        if row["series_id"] == "US.BROAD_DOLLAR":
            row["unit"] = "index_1997_100"
            row["source_field"] = "H10/H10/JRXWTFB_N.B_GOODS_ONLY"
    _write(path, expected)
    result = validate_global_financial_conditions_us_candidate(
        candidate_root, audit_path, _rehash(candidate_root, audit_path)
    )
    assert not result["passed"]
    assert "values_fields_units_exact" in result["failures"]
