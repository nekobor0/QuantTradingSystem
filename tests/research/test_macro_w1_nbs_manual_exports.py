import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from quant_trading_system.research.macro_data.w1_nbs_manual_exports import (
    MANUAL_FREEZE,
    _parse_gdp,
    _parse_industrial,
    run_manual_import,
)
from scripts.data_lake.validate_macro_w1_growth_output_full_candidate import validate_manual_candidate


ROOT = Path(__file__).resolve().parents[2]
MANUAL_DROP = ROOT / "artifacts" / "macro_r011" / "raw" / "nbs_growth_output_official" / "enablement" / "manual_drop"
PIT_A = ROOT / "artifacts" / "macro_r011" / "shadow" / "w1_growth_output_full_range_candidate.parquet"
OLD_AUDIT = ROOT / "artifacts" / "macro_r011" / "audits" / "w1_growth_output_full_range_audit.json"


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    root = tmp_path_factory.mktemp("nbs-manual")
    raw_root = root / "raw" / "nbs_growth_output_official" / "enablement"
    drop = raw_root / "manual_drop"
    drop.mkdir(parents=True)
    for source in MANUAL_DROP.glob("*.xlsx"):
        shutil.copy2(source, drop / source.name)
    output_root = root / "artifacts"
    (output_root / "audits").mkdir(parents=True)
    shutil.copy2(OLD_AUDIT, output_root / "audits" / OLD_AUDIT.name)
    result = run_manual_import(raw_root=raw_root, output_root=output_root, pit_a_candidate=PIT_A)
    return Path(result["candidate"]), Path(result["audit"]), raw_root


def _case(prepared: tuple[Path, Path, Path], tmp_path: Path) -> tuple[Path, Path]:
    candidate, audit, _ = prepared
    target_candidate = tmp_path / "candidate.parquet"
    target_audit = tmp_path / "audit.json"
    shutil.copy2(candidate, target_candidate)
    shutil.copy2(audit, target_audit)
    return target_candidate, target_audit


def _red_green(candidate: Path, audit: Path, mutate) -> None:
    originals = {candidate: candidate.read_bytes(), audit: audit.read_bytes()}
    assert validate_manual_candidate(candidate, audit)["passed"]
    mutate()
    assert not validate_manual_candidate(candidate, audit)["passed"]
    for path, payload in originals.items():
        path.write_bytes(payload)
    assert validate_manual_candidate(candidate, audit)["passed"]


def test_manual_candidate_is_exactly_581_with_pit_split(prepared):
    result = validate_manual_candidate(prepared[0], prepared[1])
    assert result["passed"], result
    assert result["rows"] == 581
    assert result["series_counts"] == {"CN.GDP.NOMINAL.YTD": 138, "CN.GDP.REAL.YOY": 134, "CN.INDUSTRIAL.VA.YOY": 309}
    assert result["pit_a_rows"] == 38
    assert result["pit_c_rows"] == 543
    assert result["manifest_count"] == 33
    assert result["candidate_raw_sha256_distinct_count"] == 33
    assert result["key_set_mismatch"] == {key: [] for key in result["key_set_mismatch"]}


def test_manual_parsers_use_index_current_quarter_and_february_regime(prepared):
    _, _, raw_root = prepared
    nominal_manifest = {"sha256": "x"}
    nominal = _parse_gdp(raw_root / "manual_drop" / "nbs-gdp-quarterly-history-original.xlsx", nominal_manifest, "gdp_nominal")
    real = _parse_gdp(raw_root / "manual_drop" / "nbs-gdp-quarterly-yoy-index-history-original.xlsx", nominal_manifest, "gdp_real")
    industrial = _parse_industrial(raw_root / "manual_drop" / "nbs-industrial-value-added-history-original.xlsx", nominal_manifest)
    assert len(nominal) == 138 and len(real) == 134 and len(industrial) == 309
    assert "CN.GDP.REAL.YOY|1992-Q1" not in {f"{row['series_id']}|{row['reference_period']}" for row in real}
    assert next(row["value"] for row in real if row["reference_period"] == "2026-Q2") == pytest.approx(4.3)
    by_period = {row["reference_period"]: row for row in industrial}
    assert by_period["2011-02"]["period_span"] == "2011-02"
    assert by_period["2012-02"]["period_span"] == "2012-02"
    assert by_period["2013-02"]["period_span"] == "2013-01/02"
    assert by_period["2013-02"]["reference_period_start"] == "2013-01"


def test_delete_candidate_row_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate).iloc[:-1]
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, mutate)


def test_audit_observed_key_change_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        document["audit"]["observed_periods"] = document["audit"]["observed_periods"][:-1]
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_2012_and_2013_february_boundary_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        mask_2012 = (frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & (frame["reference_period"] == "2012-02")
        mask_2013 = (frame["series_id"] == "CN.INDUSTRIAL.VA.YOY") & (frame["reference_period"] == "2013-02")
        frame.loc[mask_2012, "reference_period_start"] = "2012-01"
        frame.loc[mask_2012, "period_span"] = "2012-01/02"
        frame.loc[mask_2013, "reference_period_start"] = "2013-02"
        frame.loc[mask_2013, "period_span"] = "2013-02"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, mutate)


def test_fabricated_january_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
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
    _red_green(candidate, audit, mutate)


def test_fabricated_1992_real_row_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        row = frame[(frame["series_id"] == "CN.GDP.REAL.YOY")].iloc[[0]].copy()
        row["reference_period"] = "1992-Q1"
        row["reference_period_start"] = "1992-Q1"
        row["reference_period_end"] = "1992-Q1"
        row["period_span"] = "1992-Q1"
        frame = pd.concat([frame, row], ignore_index=True)
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, mutate)


def test_pit_c_backdating_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        index = frame.index[frame["pit_grade"] == "C"][0]
        frame.loc[index, ["release_at", "available_at", "tradable_at", "retrieved_at"]] = "2019-01-01T00:00:00+08:00"
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, mutate)


def test_index_cumulative_value_misuse_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        mask = (frame["series_id"] == "CN.GDP.REAL.YOY") & (frame["reference_period"] == "2024-Q2") & (frame["pit_grade"] == "C")
        frame.loc[mask, "value"] = 4.9
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, mutate)


def test_missing_manual_manifest_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        manual = next(source for source in document["audit"]["sources"] if source["source_id"] == "NBS_DATA")
        manual["raw_manifests"].pop()
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_raw_hash_tamper_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    originals = {candidate: candidate.read_bytes(), audit: audit.read_bytes()}
    document = json.loads(audit.read_text(encoding="utf-8"))
    manual = next(source for source in document["audit"]["sources"] if source["source_id"] == "NBS_DATA")
    item = manual["raw_manifests"][0]
    old_manifest = Path(item["manifest_path"])
    manifest = json.loads(old_manifest.read_text(encoding="utf-8"))
    raw_copy = tmp_path / "tampered.xlsx"
    raw_copy.write_bytes(Path(manifest["raw_path"]).read_bytes() + b"tamper")
    manifest_copy = tmp_path / "tampered.manifest.json"
    manifest["raw_path"] = str(raw_copy)
    manifest_copy.write_text(json.dumps(manifest), encoding="utf-8")
    item["manifest_path"] = str(manifest_copy)
    audit.write_text(json.dumps(document), encoding="utf-8")
    assert not validate_manual_candidate(candidate, audit)["passed"]
    for path, payload in originals.items():
        path.write_bytes(payload)
    assert validate_manual_candidate(candidate, audit)["passed"]


def test_pit_c_cannot_override_pit_a_key_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        frame = pd.read_parquet(candidate)
        duplicate = frame[frame["pit_grade"] == "A"].iloc[[0]].copy()
        manual_sha = frame[frame["pit_grade"] == "C"].iloc[0]["raw_sha256"]
        duplicate["pit_grade"] = "C"
        duplicate["source_id"] = "NBS_DATA"
        duplicate["raw_sha256"] = manual_sha
        duplicate[["release_at", "available_at", "tradable_at", "retrieved_at"]] = MANUAL_FREEZE
        frame = pd.concat([frame, duplicate], ignore_index=True)
        frame.to_parquet(candidate, index=False)
    _red_green(candidate, audit, mutate)


def test_workbook_hash_tamper_is_rejected_without_writing_candidate(prepared, tmp_path):
    raw_root = tmp_path / "raw" / "nbs_growth_output_official" / "enablement"
    drop = raw_root / "manual_drop"
    drop.mkdir(parents=True)
    for source in MANUAL_DROP.glob("*.xlsx"):
        shutil.copy2(source, drop / source.name)
    target = drop / "nbs-gdp-quarterly-yoy-index-history-original.xlsx"
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="SHA mismatch"):
        run_manual_import(raw_root=raw_root, output_root=tmp_path / "artifacts", pit_a_candidate=PIT_A)


def test_profile_values_are_derived_from_manual_xlsx_cells(prepared):
    document = json.loads(prepared[1].read_text(encoding="utf-8"))
    profiles = document["manual_route"]["profiles"]
    nonchange = profiles["nbs-GDP-nonchange-price-history-original.xlsx"]
    assert nonchange["header_periods"] == 138
    assert nonchange["observed"] == 78 and nonchange["missing"] == 60
    assert nonchange["earliest_observed"] == "2007-Q1" and nonchange["latest_observed"] == "2026-Q2"
    assert nonchange["cross_base_yoy"] is False and nonchange["canonical_rows_added"] == 0

    money = profiles["nbs-money-supply-monthly-history-original.xlsx"]
    assert set(money["row_profiles"]) == {f"{aggregate}_{measure}" for aggregate in ("M0", "M1", "M2") for measure in ("balance", "yoy")}
    assert all(row["observed"] == 320 and row["missing"] == 0 for row in money["row_profiles"].values())
    assert money["underlying_source"] == "PBOC / NBS redistribution" and money["canonical_rows_added"] == 0

    expected_fiscal = {
        "nbs-government-revenue-history-original.xlsx": {"cumulative_value": (302, 41), "cumulative_growth": (302, 41)},
        "nbs-government-spending-history-original.xlsx": {"cumulative_value": (322, 21), "cumulative_growth": (321, 22)},
    }
    for filename, expected_rows in expected_fiscal.items():
        profile = profiles[filename]
        assert profile["monthly_differencing"] is False and profile["canonical_rows_added"] == 0
        for role, (observed, missing) in expected_rows.items():
            assert profile["row_profiles"][role]["observed"] == observed
            assert profile["row_profiles"][role]["missing"] == missing


def test_nonchange_profile_earliest_tamper_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        profile = document["manual_route"]["profiles"]["nbs-GDP-nonchange-price-history-original.xlsx"]
        profile["earliest"] = "1992-Q1"
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_money_profile_count_tamper_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        profile = document["manual_route"]["profiles"]["nbs-money-supply-monthly-history-original.xlsx"]
        profile["row_profiles"]["M0_balance"]["observed"] = 319
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_fiscal_growth_count_tamper_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        profile = document["manual_route"]["profiles"]["nbs-government-revenue-history-original.xlsx"]
        profile["cumulative_growth_observed"] = 301
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_fiscal_growth_row_removal_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        profile = document["manual_route"]["profiles"]["nbs-government-spending-history-original.xlsx"]
        profile["row_profiles"].pop("cumulative_growth")
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_overlap_rounding_tamper_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        details = document["manual_route"]["overlap"]["details"]
        for item in details:
            if item["key"] in {"CN.GDP.NOMINAL.YTD|2025-Q4", "CN.GDP.NOMINAL.YTD|2026-Q1"}:
                item["category"] = "revision"
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)


def test_overlap_revision_tamper_is_red_then_green(prepared, tmp_path):
    candidate, audit = _case(prepared, tmp_path)
    def mutate():
        document = json.loads(audit.read_text(encoding="utf-8"))
        details = document["manual_route"]["overlap"]["details"]
        for item in details:
            if item["key"] == "CN.GDP.NOMINAL.YTD|2024-Q3":
                item["category"] = "rounding"
        audit.write_text(json.dumps(document), encoding="utf-8")
    _red_green(candidate, audit, mutate)
