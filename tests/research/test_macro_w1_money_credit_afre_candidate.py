import json
from pathlib import Path
import shutil

import pytest

from scripts.data_lake.validate_macro_w1_money_credit_afre_candidate import (
    AUDIT_PATH,
    CANONICAL_COLUMNS,
    CANDIDATE_ROOT,
    PAGE_TIME,
    RAW_MANIFEST_PATH,
    RAW_PATH,
    RAW_SHA256,
    SEMANTIC_SCOPE,
    SERIES_ID,
    SOURCE_URL,
    validate_money_credit_afre_candidate,
)


BLOCKED = ["CN.LOANS.RMB.FLOW", "CN.LOANS.CORP.MEDIUM_LONG.FLOW"]


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    candidate = tmp_path / "candidate"
    audit_path = tmp_path / "candidate_audit.json"
    raw_path = tmp_path / "pboc_afre.htm"
    manifest_path = tmp_path / "pboc_afre.htm.manifest.json"
    shutil.copy2(RAW_PATH, raw_path)
    manifest = json.loads(RAW_MANIFEST_PATH.read_text(encoding="utf-8"))
    _write(manifest_path, manifest)
    rows = []
    for period, value in (("2026-06", 17650), ("2026-07", -5896)):
        rows.append(
            {
                "series_id": SERIES_ID,
                "reference_period": period,
                "value": value,
                "unit": "100m_cny",
                "seasonal_adjustment": "not_seasonally_adjusted",
                "source_id": "PBOC_STATS",
                "source_record_id": "AFRE(flow)|RMB loans",
                "release_at": PAGE_TIME,
                "available_at": PAGE_TIME,
                "tradable_at": "2026-08-17T09:30:00+08:00",
                "availability_evidence": "PBOC official page timestamp",
                "retrieved_at": "2026-08-29T19:30:10+08:00",
                "vintage_id": "PBOC_AFRE_2026_08_14",
                "raw_sha256": RAW_SHA256,
                "parser_version": "manual_audit_v1",
            }
        )
    _write(
        candidate / "expected.json",
        {
            "schema_version": 2,
            "package_id": "money_credit",
            "candidate_id": "R011.W1.MONEY_CREDIT.AFRE.GOLD_CANDIDATE_V1",
            "requested_window": ["2026-06", "2026-07"],
            "canonical_columns": sorted(CANONICAL_COLUMNS),
            "row_count": 2,
            "rows": rows,
            "passed_series": [SERIES_ID],
            "blocked_series": BLOCKED,
        },
    )
    _write(
        candidate / "source_map.json",
        {
            "package_id": "money_credit",
            "sources": [
                {
                    "source_id": "PBOC_STATS",
                    "accepted": True,
                    "official_table": "AFRE(flow)",
                    "official_field": "RMB loans",
                    "semantic_scope": SEMANTIC_SCOPE,
                    "not_equivalent_to": ["CN.LOANS.RMB.FLOW"],
                    "request_url": SOURCE_URL,
                    "raw_sha256": RAW_SHA256,
                }
            ],
        },
    )
    manual = {
        "status": "GOLD_CANDIDATE_AWAITING_SOL_REVIEW",
        "passed_series": [SERIES_ID],
        "blocked_series": BLOCKED,
        "checks": {
            "direct_monthly_afre_component": True,
            "not_total_rmb_loan_flow": True,
            "no_cumulative_or_balance_differencing": True,
        },
        "failures": [],
    }
    _write(candidate / "manual_audit.json", manual)
    _write(
        audit_path,
        {
            "status": "GOLD_CANDIDATE_AWAITING_SOL_REVIEW",
            "passed_series": [SERIES_ID],
            "blocked_series": BLOCKED,
            "full_history_allowed": False,
            "formal_curated_written": False,
            "research_ready": False,
            "failures": [],
        },
    )
    return candidate, audit_path, raw_path, manifest_path


def _validate(paths: tuple[Path, Path, Path, Path]):
    return validate_money_credit_afre_candidate(*paths)


def test_afre_candidate_accepts_exact_direct_monthly_component(tmp_path: Path):
    result = _validate(_fixture(tmp_path))
    assert result["passed"], result
    assert result["post_candidate_gold_ready_count"] == 6
    assert result["gold_required_count"] == 8
    assert result["remaining_gold_missing"] == sorted(BLOCKED)


@pytest.mark.parametrize("mutation", ["legacy_alias", "wrong_value", "wrong_window", "bad_time"])
def test_afre_candidate_rejects_wrong_row_semantics(tmp_path: Path, mutation: str):
    paths = _fixture(tmp_path)
    path = paths[0] / "expected.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "legacy_alias":
        expected["rows"][0]["series_id"] = "CN.LOANS.RMB.FLOW"
    elif mutation == "wrong_value":
        expected["rows"][0]["value"] = 17651
    elif mutation == "wrong_window":
        expected["requested_window"][0] = "2026-05"
    else:
        expected["rows"][0]["available_at"] = "2026-08-14T16:29:00+08:00"
    _write(path, expected)
    assert not _validate(paths)["passed"]


def test_afre_candidate_rejects_source_scope_alias(tmp_path: Path):
    paths = _fixture(tmp_path)
    path = paths[0] / "source_map.json"
    source_map = json.loads(path.read_text(encoding="utf-8"))
    source_map["sources"][0]["semantic_scope"] = "national_total_rmb_loan_flow"
    _write(path, source_map)
    result = _validate(paths)
    assert not result["passed"]
    assert "source_map_exact" in result["failures"]


def test_afre_candidate_rejects_manual_audit_damage(tmp_path: Path):
    paths = _fixture(tmp_path)
    path = paths[0] / "manual_audit.json"
    manual = json.loads(path.read_text(encoding="utf-8"))
    manual["checks"]["not_total_rmb_loan_flow"] = False
    _write(path, manual)
    result = _validate(paths)
    assert not result["passed"]
    assert "manual_audit_fail_closed" in result["failures"]


def test_afre_candidate_rejects_premature_gate_claim(tmp_path: Path):
    paths = _fixture(tmp_path)
    audit = json.loads(paths[1].read_text(encoding="utf-8"))
    audit["full_history_allowed"] = True
    _write(paths[1], audit)
    result = _validate(paths)
    assert not result["passed"]
    assert "candidate_audit_fail_closed" in result["failures"]


def test_afre_candidate_rejects_raw_tamper(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths[2].write_bytes(paths[2].read_bytes() + b"\n")
    result = _validate(paths)
    assert not result["passed"]
    assert "raw_sha_exact" in result["failures"]
