from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "data_lake"))

import run_macro_w1_pmi_state_enablement as runner  # noqa: E402


def _gold(period: str) -> dict[str, float]:
    root = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_pmi_state" / period
    return {str(row["series_id"]): float(row["value"]) for row in json.loads((root / "expected.json").read_text(encoding="utf-8"))["rows"]}


@pytest.mark.parametrize("period", ["2026-06", "2026-07"])
def test_official_gold_is_exact(period: str) -> None:
    root = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_pmi_state" / period
    parsed = runner.parse_pmi_state_release((root / "nbs_pmi.html").read_bytes(), period)
    actual = {str(row["series_id"]): float(row["value"]) for row in parsed.rows}
    assert actual == _gold(period)
    assert len(parsed.rows) == 8
    assert parsed.structural_omissions == ()


def test_legacy_layout_does_not_fabricate_later_series() -> None:
    payload = """<html><head><meta name='PubDate' content='2013-01-31 09:30:00'></head><body>
    <table><tr><th>label</th><th>2012-12</th></tr>
    <tr><td>PMI</td><td>51.4</td></tr><tr><td>production</td><td>52.0</td></tr>
    <tr><td>new orders</td><td>52.5</td></tr><tr><td>inventory</td><td>48.0</td></tr>
    <tr><td>employment</td><td>49.0</td></tr><tr><td>delivery</td><td>50.0</td></tr></table>
    </body></html>""".encode("utf-8")
    parsed = runner.parse_pmi_state_release(payload, "2012-12")
    assert {row["series_id"] for row in parsed.rows} == {
        "CN.PMI.MFG.HEADLINE", "CN.PMI.MFG.NEW_ORDERS"
    }
    assert len(parsed.structural_omissions) == 6


def test_expected_calendar_marks_unfinished_month_not_expected() -> None:
    expected = runner.expected_series_periods("2024-08", "2026-07")
    assert all("2026-08" not in periods for periods in expected.values())
    assert len(expected["CN.PMI.MFG.HEADLINE"]) == 24
    assert len(expected["CN.PMI.NONMFG.ACTIVITY"]) == 24


@pytest.mark.parametrize(
    "status,headers,payload",
    [
        (503, {"Content-Type": "text/html"}, b"temporary"),
        (200, {"Content-Type": "text/html"}, "\u9a8c\u8bc1 captcha".encode()),
        (200, {"Content-Type": "application/json"}, b"{}"),
    ],
)
def test_http_and_pseudo_responses_are_not_success(status: int, headers: dict[str, str], payload: bytes) -> None:
    assert runner._pseudo(status, headers, payload)


def test_normal_official_html_is_not_pseudo() -> None:
    assert not runner._pseudo(200, {"Content-Type": "text/html; charset=utf-8"}, b"<html><body>PMI</body></html>")


def test_relative_release_link_keeps_official_listing_path() -> None:
    assert runner._release_url("./202607/t20260731_1964253.html") == (
        "https://www.stats.gov.cn/sj/zxfb/202607/t20260731_1964253.html"
    )
