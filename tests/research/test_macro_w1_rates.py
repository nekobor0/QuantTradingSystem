import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from scripts.data_lake.validate_macro_w1_rates_contract import validate_gold
from quant_trading_system.research.macro_data.adapters import (
    parse_cfets_repo_json,
    parse_pboc_policy_release,
)
from quant_trading_system.research.macro_data.contracts import RawSnapshot


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_rates"


def _snapshot(source_id: str, path: Path, retrieved_at: str) -> RawSnapshot:
    payload = path.read_bytes()
    return RawSnapshot(
        source_id=source_id,
        retrieved_at=datetime.fromisoformat(retrieved_at).isoformat(),
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        raw_path=str(path.resolve()),
        manifest_path=str(path.with_suffix(".manifest.json").resolve()),
        request_method="POST" if path.suffix == ".json" else "GET",
        request_url="https://official.example.invalid/fixture",
        response_status=200,
        content_type="application/json" if path.suffix == ".json" else "text/html",
    )


@pytest.mark.parametrize("period", ["2026-08-24", "2026-08-25"])
def test_cfets_repo_parser_matches_gold_exactly(period: str):
    expected = json.loads((FIXTURES / period / "expected.json").read_text(encoding="utf-8"))
    actual = []
    for series_id, index_type, filename in (
        ("CN.REPO.DR007", "markInterBankVOList", "cfets_dr007.json"),
        ("CN.REPO.R007", "markVOList", "cfets_r007.json"),
    ):
        path = FIXTURES / period / filename
        frame = parse_cfets_repo_json(
            path.read_bytes(),
            _snapshot("cfets_repo_daily", path, expected["rows"][0]["retrieved_at"]),
            requested_date=period,
            index_type=index_type,
            series_id=series_id,
        )
        actual.append(frame.iloc[0].to_dict())
    expected_repo = [row for row in expected["rows"] if row["source_id"] == "cfets_repo_daily"]
    assert pd.DataFrame(actual)[list(expected_repo[0])] .to_dict("records") == expected_repo


@pytest.mark.parametrize("period", ["2026-08-24", "2026-08-25"])
def test_pboc_omo_parser_matches_gold_exactly(period: str):
    period_root = FIXTURES / period
    expected = json.loads((period_root / "expected.json").read_text(encoding="utf-8"))
    path = period_root / "pboc_omo.html"
    result = parse_pboc_policy_release(
        path.read_bytes(),
        _snapshot("pboc_omo_release", path, expected["rows"][0]["retrieved_at"]),
    )
    expected_row = next(row for row in expected["rows"] if row["source_id"] == "pboc_omo_release")
    assert result.observations.to_dict("records") == [expected_row]
    assert result.omissions == ()


def test_pboc_mlf_post_reform_is_structural_omission():
    period = "2026-08-25"
    period_root = FIXTURES / period
    expected = json.loads((period_root / "expected.json").read_text(encoding="utf-8"))
    path = period_root / "pboc_mlf_notice.html"
    result = parse_pboc_policy_release(
        path.read_bytes(),
        _snapshot("pboc_mlf_release", path, expected["rows"][0]["retrieved_at"]),
        source_file="pboc_mlf_notice.html",
    )
    assert result.observations.empty
    assert list(result.omissions) == expected["expected_omissions"]


def test_pboc_zero_quantity_omo_is_explainable_without_rate_row():
    payload = (
        '<meta name="PubDate" content="2026-08-14 09:20:30">'
        '<p>2026年8月14日7天期逆回购操作量为零。</p>'
        '<table><tr><td>7 天</td><td>0 亿元</td><td>0 亿元</td></tr></table>'
    ).encode("utf-8")
    snapshot = RawSnapshot(
        source_id="pboc_omo_release",
        retrieved_at="2026-08-26T20:00:00+08:00",
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        raw_path="fixture.html",
        manifest_path="fixture.manifest.json",
        request_method="GET",
        request_url="https://official.example.invalid/fixture.html",
        response_status=200,
        content_type="text/html",
    )
    result = parse_pboc_policy_release(payload, snapshot, source_file="fixture.html")
    assert result.observations.empty
    assert result.event_kind == "OMO_7D_ZERO_OPERATION"
    assert result.omissions[0]["state"] == "RATE_NOT_PUBLISHED_ZERO_OPERATION"


def test_post_reform_mlf_rate_injection_is_rejected():
    period_root = FIXTURES / "2026-08-25"
    path = period_root / "pboc_mlf_notice.html"
    payload = path.read_bytes().replace(
        b"</body>", "<p>统一中标利率 2.00%</p></body>".encode("utf-8")
    )
    with pytest.raises(ValueError, match="must never be emitted"):
        parse_pboc_policy_release(
            payload,
            _snapshot("pboc_mlf_release", path, "2026-08-26T20:19:16+08:00"),
        )


def test_gold_validator_reverse_probes_fail_without_touching_gold(tmp_path: Path):
    copied = tmp_path / "w1_rates"
    shutil.copytree(FIXTURES, copied)

    expected_path = copied / "2026-08-24" / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["rows"][0]["value"] = 1.41
    expected_path.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _validator_fails(copied)

    shutil.rmtree(copied)
    shutil.copytree(FIXTURES, copied)
    dr_path = copied / "2026-08-24" / "cfets_dr007.json"
    r_path = copied / "2026-08-24" / "cfets_r007.json"
    dr_payload, r_payload = dr_path.read_bytes(), r_path.read_bytes()
    dr_path.write_bytes(r_payload)
    r_path.write_bytes(dr_payload)
    assert _validator_fails(copied)

    shutil.rmtree(copied)
    shutil.copytree(FIXTURES, copied)
    expected_path = copied / "2026-08-25" / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    injected = dict(expected["rows"][0])
    injected.update(
        series_id="CN.PBOC.MLF.1Y.RATE",
        source_id="pboc_mlf_release",
        source_record_id="2026-08-25|MLF|1Y|injected",
    )
    expected["rows"].append(injected)
    expected_path.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _validator_fails(copied)


def _validator_fails(fixture_root: Path) -> bool:
    try:
        return not bool(validate_gold(ROOT / "config" / "macro_w1_rates_contract.json", fixture_root)["passed"])
    except (KeyError, ValueError, TypeError):
        return True
