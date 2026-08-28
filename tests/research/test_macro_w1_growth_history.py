from pathlib import Path

import pytest

from quant_trading_system.research.macro_data.w1_growth_history import (
    DIRECT_RELEASE_SEEDS,
    parse_gdp_release,
    parse_industrial_release,
)


ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_growth_output"


def test_two_gold_releases_match_frozen_growth_values():
    q1 = parse_gdp_release((GOLD / "2026-Q1" / "nbs_gdp.html").read_bytes(), "2026-Q1")
    q2 = parse_gdp_release((GOLD / "2026-Q2" / "nbs_gdp.html").read_bytes(), "2026-Q2")
    i1 = parse_industrial_release((GOLD / "2026-Q1" / "nbs_industrial.html").read_bytes(), "2026-03")
    i2 = parse_industrial_release((GOLD / "2026-Q2" / "nbs_industrial.html").read_bytes(), "2026-06")
    assert [(row["series_id"], row["value"]) for row in q1.rows] == [("CN.GDP.NOMINAL.YTD", 334193.0), ("CN.GDP.REAL.YOY", 5.0)]
    assert [(row["series_id"], row["value"]) for row in q2.rows] == [("CN.GDP.NOMINAL.YTD", 695704.0), ("CN.GDP.REAL.YOY", 4.3)]
    assert i1.rows[0]["value"] == 5.7
    assert i2.rows[0]["value"] == 5.3


def test_gdp_four_value_layout_uses_ytd_amount_not_quarter_amount():
    payload = """<html><title>2025年三季度国内生产总值初步核算结果</title>
    <div>2025/10/20 09:30</div><table><tr><th>指标</th><th>三季度</th><th>前三季度</th><th>三季度</th><th>前三季度</th></tr>
    <tr><td>GDP</td><td>300000</td><td>900000</td><td>4.8</td><td>5.0</td></tr></table></html>""".encode()
    parsed = parse_gdp_release(payload, "2025-Q3")
    assert parsed.rows[0]["value"] == 900000.0
    assert parsed.rows[0]["measure_basis"] == "ytd_cumulative"
    assert parsed.rows[1]["value"] == 4.8
    assert parsed.publication_at == "2025-10-20T09:30:00+08:00"


def test_joint_january_february_has_only_february_reference_period():
    payload = """<html><title>2025年1—2月份规模以上工业增加值增长</title>
    <div>2025/03/17 10:00</div><table><tr><th>指标</th><th>1—2月</th><th>1—2月</th></tr>
    <tr><td>规模以上工业增加值</td><td>7.0</td><td>7.0</td></tr></table></html>""".encode()
    parsed = parse_industrial_release(payload, "2025-02")
    assert parsed.rows[0]["reference_period"] == "2025-02"
    assert parsed.rows[0]["period_span"] == "2025-01/02"
    with pytest.raises(ValueError, match="does not match"):
        parse_industrial_release(payload, "2025-01")


def test_release_without_official_time_is_rejected():
    payload = "<html><title>2025年一季度国内生产总值</title><table><tr><td>GDP</td><td>1</td><td>2</td></tr></table></html>".encode()
    with pytest.raises(ValueError, match="publication date and time"):
        parse_gdp_release(payload, "2025-Q1")


def test_cumulative_industrial_release_maps_to_end_month_without_january():
    payload = """<html><title>2026年1—4月份规模以上工业增加值增长5.6%</title>
    <div>2026/05/18 10:00</div><table><tr><th>指标</th><th>1—4月</th></tr>
    <tr><td>规模以上工业增加值</td><td>5.6</td></tr></table></html>""".encode()
    parsed = parse_industrial_release(payload, "2026-04")
    assert parsed.rows[0]["reference_period"] == "2026-04"
    assert parsed.rows[0]["period_span"] == "2026-04"
    with pytest.raises(ValueError, match="does not match"):
        parse_industrial_release(payload, "2026-01")


def test_direct_release_seeds_are_official_pages_only():
    assert len(DIRECT_RELEASE_SEEDS) == 13
    assert all(url.startswith("https://www.stats.gov.cn/") for url in DIRECT_RELEASE_SEEDS)
