import hashlib
import json
from pathlib import Path
from typing import Callable

import pandas as pd

from quant_trading_system.research.macro_data.contracts import CANONICAL_V2_COLUMNS
from quant_trading_system.research.macro_data.w1_execution import build_audit
from scripts.data_lake.validate_macro_w1_growth_output_candidate import validate_candidate


GDP_PERIODS = ("2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2")
INDUSTRIAL_PERIODS = ("2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07")
GDP_SERIES = ("CN.GDP.NOMINAL.YTD", "CN.GDP.REAL.YOY")


def _expected_keys() -> list[str]:
    return [f"{series}|{period}" for period in GDP_PERIODS for series in GDP_SERIES] + [f"CN.INDUSTRIAL.VA.YOY|{period}" for period in INDUSTRIAL_PERIODS]


def _fixture(tmp_path: Path) -> tuple[Path, Path, list[Path]]:
    manifest_paths: list[Path] = []
    manifest_shas: list[str] = []
    for index in range(30):
        raw = tmp_path / f"release_{index:02d}.html"
        raw.write_bytes(f"official release {index}".encode())
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        manifest = tmp_path / f"release_{index:02d}.manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "source_id": "NBS_RELEASE",
            "source_type": "release",
            "retrieved_at": "2026-08-28T00:00:00+00:00",
            "sha256": digest,
            "bytes": raw.stat().st_size,
            "raw_path": str(raw),
            "request": {"method": "GET", "url": f"https://www.stats.gov.cn/sj/zxfb/202608/t202608{index + 1:02d}_release.html"},
            "response": {"status": 200, "headers": {"content-type": "text/html"}},
            "discovery_mechanism": "official_stats_release_page_search",
            "page_publication_time_original": f"2026/08/{index + 1:02d} 09:30",
        }), encoding="utf-8")
        manifest_paths.append(manifest)
        manifest_shas.append(digest)

    rows = []
    expected = _expected_keys()
    for index, key in enumerate(expected):
        series_id, reference_period = key.split("|", 1)
        is_nominal = series_id == "CN.GDP.NOMINAL.YTD"
        is_industrial = series_id == "CN.INDUSTRIAL.VA.YOY"
        rows.append({
            "series_id": series_id,
            "reference_period": reference_period,
            "value": float(100000 + index) if is_nominal else float(index % 10),
            "unit": "100m_cny" if is_nominal else "percent_yoy",
            "seasonal_adjustment": "not_applicable",
            "source_id": "NBS_RELEASE",
            "source_record_id": f"record-{index}",
            "release_at": "2026-08-28T09:30:00+08:00",
            "available_at": "2026-08-28T09:30:00+08:00",
            "tradable_at": "2026-08-28T09:30:00+08:00",
            "availability_evidence": "official NBS release page publication timestamp",
            "retrieved_at": "2026-08-28T00:00:00+00:00",
            "vintage_id": f"v{index}",
            "raw_sha256": manifest_shas[index % 30],
            "parser_version": "test",
            "schema_version": 2,
            "reference_period_start": reference_period,
            "reference_period_end": reference_period,
            "period_span": f"{reference_period[:4]}-01/02" if is_industrial and reference_period.endswith("-02") else reference_period,
            "measure_basis": "ytd_cumulative" if is_nominal else "period_observation",
            "methodology_version": "test",
            "regime_id": "growth_output_bounded",
            "pit_grade": "A",
            "license_scope": "internal_research",
        })
    candidate = tmp_path / "candidate.parquet"
    pd.DataFrame(rows, columns=CANONICAL_V2_COLUMNS).to_parquet(candidate, index=False)
    audit = build_audit(
        package_id="growth_output", run_mode="shadow", start="2024-08", end="2026-07",
        expected=expected, observed=expected,
        sources=[{"raw_manifests": [{"manifest_path": str(path)} for path in manifest_paths]}],
        blockers=[], unexplained_missing=[], structural_omissions=[], raw_hashes_valid=True,
    )
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({"audit": audit}), encoding="utf-8")
    return candidate, audit_path, manifest_paths


def _red_green(candidate: Path, audit_path: Path, paths: list[Path], mutate: Callable[[], None]) -> None:
    originals = {path: path.read_bytes() for path in [candidate, audit_path, *paths]}
    assert validate_candidate(candidate, audit_path)["passed"]
    mutate()
    red = validate_candidate(candidate, audit_path)
    assert not red["passed"], red
    for path, payload in originals.items():
        path.write_bytes(payload)
    green = validate_candidate(candidate, audit_path)
    assert green["passed"], green


def _load_audit(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_audit(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def test_complete_fixture_is_green_and_reports_independent_counts(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    result = validate_candidate(candidate, audit)
    assert result["passed"], result
    assert result["rows"] == 38
    assert result["series_counts"] == {"CN.GDP.NOMINAL.YTD": 8, "CN.GDP.REAL.YOY": 8, "CN.INDUSTRIAL.VA.YOY": 22}
    assert result["manifest_count"] == 30
    assert result["expected_periods_independent_count"] == 38
    assert result["key_set_mismatch"] == {"candidate_only": [], "audit_observed_only": [], "expected_only_in_candidate": [], "expected_only_in_audit_observed": [], "candidate_vs_audit": {"candidate_only": [], "audit_observed_only": []}}
    assert result["pit_failure_count"] == 0
    assert len(manifests) == 30


def test_delete_candidate_row_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        pd.read_parquet(candidate).iloc[:-1].to_parquet(candidate, index=False)
    _red_green(candidate, audit, manifests, mutate)


def test_audit_observed_less_and_more_are_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate_less() -> None:
        document = _load_audit(audit)
        document["audit"]["observed_periods"] = document["audit"]["observed_periods"][:-1]
        _save_audit(audit, document)
    _red_green(candidate, audit, manifests, mutate_less)

    def mutate_more() -> None:
        document = _load_audit(audit)
        document["audit"]["observed_periods"] = document["audit"]["observed_periods"] + ["EXTRA|2026-Q2"]
        _save_audit(audit, document)
    _red_green(candidate, audit, manifests, mutate_more)


def test_requested_window_tamper_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        document = _load_audit(audit)
        document["audit"]["requested_window"]["start"] = "2024-09"
        _save_audit(audit, document)
    _red_green(candidate, audit, manifests, mutate)


def test_blocked_or_unexplained_audit_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        document = _load_audit(audit)
        document["audit"]["blocked"] = True
        document["audit"]["blockers"] = [{"code": "TEST"}]
        document["audit"]["unexplained_missing"] = ["CN.GDP.REAL.YOY|2026-Q2"]
        _save_audit(audit, document)
    _red_green(candidate, audit, manifests, mutate)


def test_candidate_raw_sha_not_in_manifest_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        frame = pd.read_parquet(candidate)
        frame.loc[0, "raw_sha256"] = "f" * 64
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, manifests, mutate)


def test_manifest_publication_empty_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        document = json.loads(manifests[0].read_text(encoding="utf-8"))
        document["page_publication_time_original"] = ""
        manifests[0].write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, manifests, mutate)


def test_pit_mismatch_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        frame = pd.read_parquet(candidate)
        frame.loc[0, "available_at"] = "2026-08-28T09:31:00+08:00"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, manifests, mutate)


def test_missing_manifest_is_red_then_green(tmp_path: Path):
    candidate, audit, manifests = _fixture(tmp_path)
    def mutate() -> None:
        document = _load_audit(audit)
        document["audit"]["sources"][0]["raw_manifests"] = document["audit"]["sources"][0]["raw_manifests"][:-1]
        _save_audit(audit, document)
    _red_green(candidate, audit, manifests, mutate)
