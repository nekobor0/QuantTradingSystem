from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from quant_trading_system.research.macro_data import w1_prices_history as prices  # noqa: E402


def _cpi_html(period: str, all_yoy: float, core_yoy: float) -> bytes:
    year, month = period.split("-")
    return f"""<html><head><meta name='ArticleTitle' content='{year}年{int(month)}月份居民消费价格同比上涨{all_yoy}%'><meta name='PubDate' content='{int(year)+0:04d}/{int(month)+1:02d}/09 09:30'></head><body><table><tr><th>指标</th><th>同比涨跌幅（%）</th></tr><tr><td>居民消费价格</td><td>{all_yoy}</td></tr><tr><td>不包括食品和能源</td><td>{core_yoy}</td></tr></table></body></html>""".encode()


def _ppi_html(period: str, yoy: float, mom: float, input_yoy: float) -> bytes:
    year, month = period.split("-")
    return f"""<html><head><meta name='ArticleTitle' content='{year}年{int(month)}月份工业生产者出厂价格同比上涨{yoy}%'><meta name='PubDate' content='{int(year):04d}/{int(month)+1:02d}/09 09:30'></head><body><table><tr><th>指标</th><th>环比涨跌幅（%）</th><th>同比涨跌幅（%）</th></tr><tr><td>一、工业生产者出厂价格</td><td>{mom}</td><td>{yoy}</td></tr><tr><td>二、工业生产者购进价格</td><td>0.0</td><td>{input_yoy}</td></tr></table></body></html>""".encode()


def _interpretation_html(period: str, base_year: int) -> bytes:
    year, month = period.split("-")
    return f"""<html><head><meta name='ArticleTitle' content='国家统计局城市司首席统计师解读{year}年{int(month)}月份CPI和PPI数据'><meta name='PubDate' content='{int(year):04d}/{int(month)+1:02d}/09 09:30'></head><body>{base_year}年为基期，CPI和PPI统计制度说明。</body></html>""".encode()


def _manifest(root: Path, source_type: str, period: str, url: str, payload: bytes) -> dict[str, object]:
    return prices._capture(root, source_id=prices.SOURCE_ID, source_type=source_type, reference_period=period, request_method="GET", request_url=url, parameters=None, status=200, headers={"Content-Type": "text/html"}, payload=payload, error=None)


def test_gold_layout_parser_exact_values_without_gold_dependency() -> None:
    cpi = prices.parse_cpi_release(_cpi_html("2026-06", 1.0, 1.0), "2026-06")
    ppi = prices.parse_ppi_release(_ppi_html("2026-06", 4.1, -0.3, 6.4), "2026-06")
    assert cpi["values"] == {"CN.CPI.ALL.YOY": 1.0, "CN.CPI.CORE.YOY": 1.0}
    assert ppi["values"] == {"CN.PPI.ALL.YOY": 4.1, "CN.PPI.ALL.MOM": -0.3, "CN.PPIRM.ALL.YOY": 6.4}


def test_parser_requires_named_headers_and_fields() -> None:
    bad = _ppi_html("2026-06", 4.1, -0.3, 6.4).replace("工业生产者购进价格".encode(), "工业生产者购进价".encode())
    with pytest.raises(ValueError, match="named output/input"):
        prices.parse_ppi_release(bad, "2026-06")


def test_capture_manifest_contains_period_type_url_and_hash(tmp_path: Path) -> None:
    payload = b"<html>official</html>"
    url = "https://www.stats.gov.cn/sj/zxfb/202607/t.html"
    manifest = _manifest(tmp_path, "official_cpi_release", "2026-06", url, payload)
    manifest_path = Path(str(manifest["manifest_path"]))
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert loaded["source_type"] == "official_cpi_release"
    assert loaded["reference_period"] == "2026-06"
    assert loaded["request"]["url"] == url
    assert loaded["sha256"] == hashlib.sha256(payload).hexdigest()


def test_pubdate_without_timezone_is_interpreted_as_shanghai() -> None:
    parsed = prices.parse_cpi_release(_cpi_html("2026-06", 1.0, 0.9), "2026-06")
    assert parsed["publication_at"] == "2026-07-09T09:30:00+08:00"
    assert parsed["publication_at"].endswith("+08:00")


def test_search_cutoff_uses_real_calendar_month_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_fetch(_root: Path, **kwargs: object) -> tuple[dict[str, object], bytes]:
        calls.append(dict(kwargs["parameters"]))
        return {"response": {"status": 200}}, b'{"totalHits": 0, "resultDocs": []}'

    monkeypatch.setattr(prices, "_fetch_capture", fake_fetch)
    for start, end, expected_end in (
        ("2024-01", "2024-01", "2024-02-29"),
        ("2025-01", "2025-01", "2025-02-28"),
        ("2024-12", "2024-12", "2025-01-31"),
    ):
        prices._search_query(tmp_path / start, "term", start, end)
        assert calls[-1]["endDateStr"] == expected_end
        assert "-31" not in calls[-1]["endDateStr"] or expected_end.endswith("-31")


def test_atomic_capture_survives_long_path(tmp_path: Path) -> None:
    long_root = tmp_path / ("prices_long_path_" * 12)
    payload = b"<html>long-path-official</html>"
    manifest = _manifest(long_root, "official_cpi_release", "2026-06", "https://www.stats.gov.cn/long.html", payload)
    manifest_path = Path(str(manifest["manifest_path"]))
    loaded = json.loads(prices._read_bytes(manifest_path).decode("utf-8"))
    raw_path = prices._manifest_raw_path(manifest_path, loaded)
    assert prices._read_bytes(raw_path) == payload
    assert loaded["raw_path"] == raw_path.name


def test_raw_hash_tamper_is_red_then_green_after_restore(tmp_path: Path) -> None:
    payload = b"<html>immutable-official</html>"
    manifest = _manifest(tmp_path, "official_cpi_release", "2026-06", "https://www.stats.gov.cn/immutable.html", payload)
    manifest_path = Path(str(manifest["manifest_path"]))
    raw_path = prices._manifest_raw_path(manifest_path, json.loads(prices._read_bytes(manifest_path).decode("utf-8")))
    with open(prices._native_path(raw_path), "wb") as handle:
        handle.write(b"tampered")
    assert prices._raw_hash_audit(tmp_path)["valid"] is False
    with open(prices._native_path(raw_path), "wb") as handle:
        handle.write(payload)
    assert prices._raw_hash_audit(tmp_path)["valid"] is True


def test_synthetic_bounded_audit_has_five_rows_per_period(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    periods = ["2026-06", "2026-07"]
    payloads: dict[str, tuple[dict[str, object], bytes]] = {}
    candidates: dict[str, dict[str, dict[str, str]]] = {"cpi": {}, "ppi": {}, "interpretation": {}}
    for period in periods:
        cpi_url = f"https://www.stats.gov.cn/cpi/{period}.html"
        ppi_url = f"https://www.stats.gov.cn/ppi/{period}.html"
        int_url = f"https://www.stats.gov.cn/int/{period}.html"
        cpi_manifest = _manifest(tmp_path, "official_cpi_release", period, cpi_url, _cpi_html(period, 1.0, 0.9))
        ppi_manifest = _manifest(tmp_path, "official_ppi_release", period, ppi_url, _ppi_html(period, 4.1, -0.3, 6.4))
        int_manifest = _manifest(tmp_path, "official_interpretation", period, int_url, _interpretation_html(period, 2025))
        payloads[cpi_url] = (cpi_manifest, _cpi_html(period, 1.0, 0.9))
        payloads[ppi_url] = (ppi_manifest, _ppi_html(period, 4.1, -0.3, 6.4))
        payloads[int_url] = (int_manifest, _interpretation_html(period, 2025))
        candidates["cpi"][period] = {"url": cpi_url, "title": ""}
        candidates["ppi"][period] = {"url": ppi_url, "title": ""}
        candidates["interpretation"][period] = {"url": int_url, "title": ""}

    monkeypatch.setattr(prices, "_discover", lambda *_args, **_kwargs: {"listing": {"urls": [], "periods": periods, "failures": []}, "search": [], "candidates": candidates, "query_start": periods[0]})
    monkeypatch.setattr(prices, "_methodology", lambda *_args, **_kwargs: ([{"regime": "2025_base_effective_2026-01", "base_year": "2025", "effective_period_start": "2026-01"}], []))
    monkeypatch.setattr(prices, "_fetch_capture", lambda _root, **kwargs: payloads[str(kwargs["url"])])
    result = prices.run_history_shadow(tmp_path, periods[0], periods[-1])
    audit = result["audit"]
    source = audit["sources"][0]
    assert result["validation"]["passed"]
    assert audit["observed_periods"] == periods
    assert source["successful_parse"]["rows"] == 10
    assert source["raw_hash"]["valid"]
    assert audit["unexplained_missing"] == []
    assert audit["duplicate_primary_keys"] == 0
    assert audit["value_domain_failures"] == 0
    assert source["history_scope"]["pit_a_window"]["start"] == "2021-01"
    assert source["history_scope"]["pre_2021_status"] == "deferred_pit_c_exploratory_not_acquired"
