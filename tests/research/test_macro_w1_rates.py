import hashlib
import json
import os
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
from quant_trading_system.research.macro_data.backfill import _repo_outcome_status, _unexplained_repo_dates
from quant_trading_system.research.macro_data.contracts import RawSnapshot
from scripts.data_lake.run_macro_w1_rates_full import count_independent_cfets_paths


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(os.environ.get("QTS_W1_GOLD_FIXTURES", ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_rates"))
GOLD_TRADING_DATES = frozenset({"2026-08-24", "2026-08-25", "2026-08-26"})
LOCAL_GOLD_AVAILABLE = all(
    (FIXTURES / period / "expected.json").is_file()
    for period in ("2026-08-24", "2026-08-25")
)
requires_local_gold = pytest.mark.skipif(not LOCAL_GOLD_AVAILABLE, reason="ignored local W1 Gold fixtures are not present")


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


def _inline_snapshot(source_id: str, payload: bytes) -> RawSnapshot:
    return RawSnapshot(
        source_id=source_id,
        retrieved_at="2026-10-10T20:00:00+08:00",
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        raw_path="synthetic.fixture",
        manifest_path="synthetic.manifest.json",
        request_method="POST" if source_id == "cfets_repo_daily" else "GET",
        request_url="https://official.example.invalid/synthetic",
        response_status=200,
        content_type="application/json" if source_id == "cfets_repo_daily" else "text/html",
    )


def test_cfets_repo_uses_explicit_strategy_calendar_across_holiday_gap():
    payload = json.dumps({
        "head": {"rep_code": "200"},
        "data": {"lastDate": "2026-09-30"},
        "records": [{"instrmntCd": "DR007", "wghtdAvgRepoRate": "1.50"}],
    }).encode("utf-8")
    frame = parse_cfets_repo_json(
        payload,
        _inline_snapshot("cfets_repo_daily", payload),
        requested_date="2026-09-30",
        index_type="markInterBankVOList",
        series_id="CN.REPO.DR007",
        strategy_trading_dates=frozenset({"2026-09-30", "2026-10-01", "2026-10-02", "2026-10-09"}),
        holidays=frozenset({"2026-10-01", "2026-10-02"}),
    )
    assert frame.iloc[0]["tradable_at"] == "2026-10-09T09:30:00+08:00"


def test_repo_missing_classification_rejects_partial_and_transport_failures():
    empty_requests = [
        {
            "series_id": series_id,
            "status": "QUARANTINED",
            "reason": "ValueError: CFETS response contains no records",
        }
        for series_id in ("CN.REPO.DR007", "CN.REPO.R007")
    ]
    partial_requests = [
        {"series_id": "CN.REPO.DR007", "status": "SUCCESS"},
        {
            "series_id": "CN.REPO.R007",
            "status": "QUARANTINED",
            "reason": "ValueError: non-200 response: 503",
        },
    ]
    assert _repo_outcome_status(empty_requests) == "OFFICIAL_EMPTY_RECORDS"
    assert _repo_outcome_status(partial_requests) == "UNEXPLAINED_QUARANTINED"
    outcomes = {
        "2026-08-11": {"status": "OFFICIAL_EMPTY_RECORDS"},
        "2026-08-12": {"status": "UNEXPLAINED_QUARANTINED"},
    }
    assert _unexplained_repo_dates(list(outcomes), outcomes) == ["2026-08-12"]


def test_three_retries_of_one_cfets_endpoint_are_one_mechanism():
    records = [
        {
            "url": "https://www.chinamoney.com.cn/ags/ms/cm-u-dlrp/PrDlyBltn",
            "method": "POST",
            "params": {"lang": "cn", "publishedTime": "2200", "searchDate": date, "indexType": index_type},
        }
        for date, index_type in (("2026-07-27", "markInterBankVOList"), ("2026-07-28", "markInterBankVOList"), ("2026-07-29", "markVOList"))
    ]
    assert count_independent_cfets_paths(records) == 1


def test_synthetic_parser_probes_run_without_gold_files():
    payload = json.dumps({
        "head": {"rep_code": "200"},
        "data": {"lastDate": "2026-10-09"},
        "records": [{"instrmntCd": "DR007", "wghtdAvgRepoRate": "1.50"}],
    }).encode("utf-8")
    frame = parse_cfets_repo_json(
        payload,
        _inline_snapshot("cfets_repo_daily", payload),
        requested_date="2026-10-09",
        index_type="markInterBankVOList",
        series_id="CN.REPO.DR007",
        strategy_trading_dates=frozenset({"2026-10-09", "2026-10-12"}),
    )
    assert frame.iloc[0]["value"] == 1.5


def test_synthetic_post_reform_mlf_omission_and_rate_injection():
    payload = (
        '<meta name="PubDate" content="2026-08-25 09:20:30">'
        "<p>2026\u5e748\u670825\u65e5\u4e2d\u56fd\u4eba\u6c11\u94f6\u884c"
        "\u5c06\u5f00\u5c55\u4e2d\u671f\u501f\u8d37\u4fbf\u5229\u64cd\u4f5c\uff0c"
        "\u671f\u9650\u4e3a1\u5e74\u671f\uff0c\u91c7\u7528\u591a\u91cd\u4ef7\u4f4d\u4e2d\u6807\u3002</p>"
    ).encode("utf-8")
    result = parse_pboc_policy_release(
        payload,
        _inline_snapshot("pboc_mlf_release", payload),
        source_file="synthetic_mlf.html",
    )
    assert result.observations.empty
    assert result.omissions[0]["state"] == "UNIFIED_RATE_STRUCTURALLY_UNDEFINED"

    injected = payload + "<p>\u7edf\u4e00\u4e2d\u6807\u5229\u7387 2.00%</p>".encode("utf-8")
    with pytest.raises(ValueError, match="must never be emitted"):
        parse_pboc_policy_release(
            injected,
            _inline_snapshot("pboc_mlf_release", injected),
            source_file="synthetic_mlf.html",
        )



@pytest.mark.parametrize("period", ["2026-08-24", "2026-08-25"])
@requires_local_gold
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
            strategy_trading_dates=GOLD_TRADING_DATES,
        )
        actual.append(frame.iloc[0].to_dict())
    expected_repo = [row for row in expected["rows"] if row["source_id"] == "cfets_repo_daily"]
    assert pd.DataFrame(actual)[list(expected_repo[0])] .to_dict("records") == expected_repo


@pytest.mark.parametrize("period", ["2026-08-24", "2026-08-25"])
@requires_local_gold
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


@requires_local_gold
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


@requires_local_gold
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


@requires_local_gold
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
