import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.macro_data.contracts import CANONICAL_V2_COLUMNS
from quant_trading_system.research.macro_data.w1_execution import build_audit
from quant_trading_system.research.macro_data.w1_growth_full_history import expected_keys, expected_periods, validate_industrial_layout, write_source_map
from scripts.data_lake.validate_macro_w1_growth_output_full_candidate import validate_full_candidate


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    output_root = tmp_path / "artifacts"
    source_map = write_source_map(output_root)
    raw = tmp_path / "release.html"
    raw.write_bytes(b"official NBS release fixture")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    manifest = tmp_path / "release.manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "source_id": "NBS_RELEASE",
        "source_type": "release",
        "retrieved_at": "2026-08-28T00:00:00+00:00",
        "sha256": digest,
        "bytes": raw.stat().st_size,
        "raw_path": str(raw),
        "request": {"method": "GET", "url": "https://www.stats.gov.cn/sj/zxfb/202608/t20260828_fixture.html"},
        "response": {"status": 200, "headers": {"content-type": "text/html"}},
        "discovery_mechanism": "official_nbs_source_map_probe",
        "page_publication_time_original": "2026/08/28 09:30",
    }), encoding="utf-8")
    rows = [{
        "series_id": "CN.GDP.NOMINAL.YTD",
        "reference_period": "1992-Q1",
        "value": 100.0,
        "unit": "100m_cny",
        "seasonal_adjustment": "not_applicable",
        "source_id": "NBS_RELEASE",
        "source_record_id": "fixture-record",
        "release_at": "2026-08-28T09:30:00+08:00",
        "available_at": "2026-08-28T09:30:00+08:00",
        "tradable_at": "2026-08-28T09:30:00+08:00",
        "availability_evidence": "official NBS release publication timestamp",
        "retrieved_at": "2026-08-28T00:00:00+00:00",
        "vintage_id": "fixture-vintage",
        "raw_sha256": digest,
        "parser_version": "fixture",
        "schema_version": 2,
        "reference_period_start": "1992-Q1",
        "reference_period_end": "1992-Q1",
        "period_span": "1992-Q1",
        "measure_basis": "ytd_cumulative",
        "methodology_version": "fixture",
        "regime_id": "growth_output_full_history",
        "pit_grade": "A",
        "license_scope": "internal_research",
    }]
    candidate = tmp_path / "candidate.parquet"
    pd.DataFrame(rows, columns=CANONICAL_V2_COLUMNS).to_parquet(candidate, index=False)
    observed = ["CN.GDP.NOMINAL.YTD|1992-Q1"]
    missing = sorted(set(expected_keys()) - set(observed))
    structural = [{"series_id": "CN.INDUSTRIAL.VA.YOY", "period": f"{year}-01", "reason": "January single-month value is not officially published"} for year in range(2005, 2027)]
    audit = build_audit(
        package_id="growth_output", run_mode="full", start="1992-Q1", end="2026-07",
        expected=expected_keys(), observed=observed,
        sources=[{"source_id": "NBS_RELEASE", "raw_manifests": [{"manifest_path": str(manifest), "pit_grade": "A"}]}],
        blockers=[{"code": "OFFICIAL_HISTORY_INCOMPLETE", "detail": "fixture"}],
        unexplained_missing=missing, structural_omissions=structural, raw_hashes_valid=True,
    )
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({"audit": audit}), encoding="utf-8")
    return candidate, audit_path, source_map, manifest


def _complete_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    frame = pd.read_parquet(candidate)
    template = frame.iloc[0].to_dict()
    digest = template["raw_sha256"]
    rows = []
    for index, key in enumerate(expected_keys()):
        series, period = key.split("|", 1)
        row = dict(template)
        row["series_id"] = series
        row["reference_period"] = period
        row["source_record_id"] = f"complete-{index}"
        row["vintage_id"] = f"complete-{index}"
        row["raw_sha256"] = digest
        row["unit"] = "100m_cny" if series == "CN.GDP.NOMINAL.YTD" else "percent_yoy"
        row["measure_basis"] = "ytd_cumulative" if series == "CN.GDP.NOMINAL.YTD" else "period_observation"
        row["reference_period_start"] = f"{period[:4]}-01" if series == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-02") else period
        row["reference_period_end"] = period
        joint = series == "CN.INDUSTRIAL.VA.YOY" and period.endswith("-02") and int(period[:4]) >= 2012
        row["reference_period_start"] = f"{period[:4]}-01" if joint else period
        row["period_span"] = f"{period[:4]}-01/02" if joint else period
        row["value"] = float(index + 1)
        rows.append(row)
    pd.DataFrame(rows, columns=CANONICAL_V2_COLUMNS).to_parquet(candidate, index=False)
    document = json.loads(audit.read_text(encoding="utf-8"))
    document["audit"]["observed_periods"] = expected_keys()
    document["audit"]["unexplained_missing"] = []
    document["audit"]["blockers"] = []
    document["audit"]["blocked"] = False
    audit.write_text(json.dumps(document), encoding="utf-8")
    return candidate, audit, source_map, manifest


def _red_green(candidate: Path, audit: Path, source_map: Path, manifest: Path, mutate) -> None:
    originals = {path: path.read_bytes() for path in (candidate, audit, source_map, manifest)}
    baseline = validate_full_candidate(candidate, audit, source_map)
    assert baseline["passed"], json.dumps(baseline, ensure_ascii=False, indent=2)
    mutate()
    assert not validate_full_candidate(candidate, audit, source_map)["passed"]
    for path, payload in originals.items():
        path.write_bytes(payload)
    assert validate_full_candidate(candidate, audit, source_map)["passed"]


def test_blocked_partial_fixture_is_green_and_reports_independent_scope(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    result = validate_full_candidate(candidate, audit, source_map)
    assert result["passed"], result
    assert result["expected_periods_independent_count"] == 597
    assert result["observed_cells"] == 1
    assert result["unexplained_missing_count"] == 596
    assert result["series_counts"]["CN.GDP.NOMINAL.YTD"] == 1
    assert result["pit_failure_count"] == 0
    assert result["manifest_count"] == 1


def test_scope_counts_and_february_joint_periods_are_frozen():
    periods = expected_periods()["industrial"]
    assert len(expected_keys()) == 597
    assert len(periods) == 321
    assert "2025-02" in periods and "2026-02" in periods
    assert "2025-01" not in periods and "2026-01" not in periods


def test_delete_2012_plus_february_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        frame = frame[~((frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & (frame["reference_period"] == "2025-02"))]
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_marking_2012_plus_february_structural_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        document["audit"]["structural_omissions"].append({"series_id": "CN.INDUSTRIAL.VA.YOY", "period": "2025-02", "reason": "February release is Jan-Feb cumulative"})
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_inserting_2005_january_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        row = frame.iloc[[0]].copy()
        row["series_id"] = "CN.INDUSTRIAL.VA.YOY"
        row["reference_period"] = "2005-01"
        row["reference_period_start"] = "2005-01"
        row["reference_period_end"] = "2005-01"
        row["period_span"] = "2005-01"
        frame = pd.concat([frame, row], ignore_index=True)
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_february_rows_require_joint_span_in_complete_fixture(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    frame = pd.read_parquet(candidate)
    feb = frame[(frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & frame["reference_period"].isin(["2025-02", "2026-02"])]
    assert len(feb) == 2
    assert set(feb["period_span"]) == {"2025-01/02", "2026-01/02"}


def test_2011_february_is_independent_in_complete_fixture(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    frame = pd.read_parquet(candidate)
    feb = frame[(frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & (frame["reference_period"] == "2011-02")].iloc[0]
    assert feb["reference_period_start"] == "2011-02"
    assert feb["reference_period_end"] == "2011-02"
    assert feb["period_span"] == "2011-02"


def test_2011_february_marked_joint_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        mask = (frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & (frame["reference_period"] == "2011-02")
        frame.loc[mask, "reference_period_start"] = "2011-01"
        frame.loc[mask, "period_span"] = "2011-01/02"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_2012_february_marked_single_month_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        mask = (frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & (frame["reference_period"] == "2012-02")
        frame.loc[mask, "reference_period_start"] = "2012-02"
        frame.loc[mask, "period_span"] = "2012-02"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_february_layout_mismatch_is_rejected():
    independent = "<html><title>2011年1—2月份规模以上工业增加值增长</title></html>".encode()
    joint = "<html><title>2012年2月份规模以上工业增加值增长</title></html>".encode()
    import pytest
    with pytest.raises(ValueError, match="independent 2月份"):
        validate_industrial_layout(independent, "2011-02")
    with pytest.raises(ValueError, match="1—2月份 joint"):
        validate_industrial_layout(joint, "2012-02")


def test_total_or_industrial_denominator_tamper_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate_total():
        document = json.loads(source_map.read_text(encoding="utf-8"))
        document["scope"]["expected_key_count"] = 596
        source_map.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, source_map, manifest, mutate_total)

    def mutate_industrial():
        document = json.loads(source_map.read_text(encoding="utf-8"))
        document["scope"]["industrial"]["expected_cells"] = 320
        source_map.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, source_map, manifest, mutate_industrial)


def test_audit_expected_set_tamper_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _complete_fixture(tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        document["audit"]["expected_periods"] = document["audit"]["expected_periods"][:-1]
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_wrong_pit_grade_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        frame.loc[0, "pit_grade"] = "C"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_retrospective_availability_backfill_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        frame.loc[0, "available_at"] = "1992-03-31T00:00:00+08:00"
        frame.loc[0, "tradable_at"] = "1992-03-31T00:00:00+08:00"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_single_quarter_gdp_as_ytd_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        frame.loc[0, "measure_basis"] = "period_observation"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_january_industrial_row_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        frame.loc[0, "series_id"] = "CN.INDUSTRIAL.VA.YOY"
        frame.loc[0, "reference_period"] = "1998-01"
        frame.loc[0, "reference_period_start"] = "1998-01"
        frame.loc[0, "reference_period_end"] = "1998-01"
        frame.loc[0, "period_span"] = "1998-01"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_missing_manifest_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        document["audit"]["sources"][0]["raw_manifests"] = []
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, source_map, manifest, mutate)


def test_raw_tamper_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    raw = Path(json.loads(manifest.read_text(encoding="utf-8"))["raw_path"])
    originals = {path: path.read_bytes() for path in (candidate, audit, source_map, manifest, raw)}
    assert validate_full_candidate(candidate, audit, source_map)["passed"]
    raw.write_bytes(b"tampered")
    assert not validate_full_candidate(candidate, audit, source_map)["passed"]
    for path, payload in originals.items():
        path.write_bytes(payload)
    assert validate_full_candidate(candidate, audit, source_map)["passed"]


def test_scope_denominator_shrink_is_red_then_green(tmp_path: Path):
    candidate, audit, source_map, manifest = _fixture(tmp_path)
    def mutate():
        document = json.loads(source_map.read_text(encoding="utf-8"))
        document["expected_keys"] = document["expected_keys"][:-1]
        source_map.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, source_map, manifest, mutate)
