from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_trading_system.research.macro_data.adapters import parse_pmi_release, parse_shibor
from quant_trading_system.research.macro_data.contracts import (
    RawSnapshot,
    capture_raw_snapshot,
    load_registry,
)
from quant_trading_system.research.macro_data.pipeline import validate_canonical


REGISTRY = Path(__file__).resolve().parents[2] / "config" / "macro_sample_registry.json"


def _snapshot(source_id: str, digest: str = "a" * 64) -> RawSnapshot:
    return RawSnapshot(
        source_id=source_id,
        retrieved_at="2026-08-25T12:00:00+00:00",
        sha256=digest,
        bytes=10,
        raw_path="raw",
        manifest_path="manifest",
        request_method="GET",
        request_url="https://example.test",
        response_status=200,
        content_type="application/json",
    )


def test_registry_has_unique_sources_and_complete_sample_series():
    registry = load_registry(REGISTRY)
    assert {item.source_id for item in registry.sources} == {
        "cfets_shibor_public", "nbs_pmi_release_archive", "nbs_national_data_pmi",
    }
    assert len(registry.series_for_source("cfets_shibor_public")) == 8
    assert len(registry.series_for_source("nbs_pmi_release_archive")) == 6


def test_raw_snapshot_is_content_addressed_and_redacts_metadata(tmp_path):
    snapshot = capture_raw_snapshot(
        output_root=tmp_path,
        source_id="official",
        payload=b"same payload",
        retrieved_at=datetime(2026, 8, 25, 1, 2, 3, tzinfo=timezone.utc),
        request_method="GET",
        request_url="https://example.test/data?token=secret",
        response_status=200,
        response_headers={"Content-Type": "application/json", "Set-Cookie": "secret"},
        extension="json",
    )
    manifest = Path(snapshot.manifest_path).read_text(encoding="utf-8")
    assert snapshot.sha256 in snapshot.raw_path
    assert "REDACTED" in manifest
    assert "Set-Cookie" not in manifest and "secret" not in manifest


def test_shibor_parser_emits_eight_tenors_with_conservative_release_time():
    payload = b'''{
      "head":{"rep_code":"200"},
      "records":[{"showDateCN":"2026-08-25","ON":"1.4350","1W":"1.4535",
      "2W":"1.4420","1M":"1.4178","3M":"1.4300","6M":"1.4510",
      "9M":"1.4700","1Y":"1.4800"}]}
    '''
    registry = load_registry(REGISTRY)
    frame = parse_shibor(
        payload, _snapshot("cfets_shibor_public"),
        registry.series_for_source("cfets_shibor_public"),
    )
    assert len(frame) == 8
    assert frame["series_id"].nunique() == 8
    assert set(frame["release_at"].str[-6:]) == {"+08:00"}
    assert set(frame["availability_evidence"]) == {
        "official_scheduled_publication_time_not_observed_latency"
    }
    assert set(frame["tradable_at"]) == {"2026-08-25T20:00:00+08:00"}


def test_pmi_parser_keeps_rolling_history_in_one_observed_vintage():
    rows = "".join(
        f"<tr><td>2025年{month}月</td><td>49.0</td><td>50.0</td><td>48.0</td>"
        "<td>47.0</td><td>46.0</td><td>51.0</td></tr>"
        for month in range(1, 11)
    )
    payload = (
        "<html><body><p>发布时间：2026-07-31 09:30</p><table>"
        "<tr><th>日期</th><th>PMI</th><th>生产</th><th>新订单</th>"
        "<th>原材料库存</th><th>从业人员</th><th>供应商配送时间</th></tr>"
        f"{rows}</table></body></html>"
    ).encode()
    frame = parse_pmi_release(payload, _snapshot("nbs_pmi_release_archive"))
    assert len(frame) == 60
    assert frame["series_id"].nunique() == 6
    assert frame["vintage_id"].nunique() == 1
    assert frame["available_at"].nunique() == 1
    assert frame.iloc[0]["available_at"] == "2026-07-31T09:30:00+08:00"


def test_pmi_parser_supports_legacy_horizontal_release_table():
    payload = """
    <html><body><p>2012/03/01 09:00</p><table>
      <tr><td>指标</td><td>2012年2月</td><td>2012年1月</td></tr>
      <tr><td>PMI</td><td>51.0</td><td>50.5</td></tr>
      <tr><td>生产</td><td>53.8</td><td>53.6</td></tr>
      <tr><td>新订单</td><td>51.0</td><td>50.4</td></tr>
      <tr><td>原材料库存</td><td>48.8</td><td>49.7</td></tr>
      <tr><td>从业人员</td><td>49.5</td><td>47.1</td></tr>
      <tr><td>供应商配送时间</td><td>50.3</td><td>49.7</td></tr>
    </table></body></html>
    """.encode()
    frame = parse_pmi_release(payload, _snapshot("nbs_pmi_release_archive"))
    assert len(frame) == 12
    assert set(frame["reference_period"]) == {"2012-01", "2012-02"}
    assert set(frame["release_at"]) == {"2012-03-01T09:00:00+08:00"}
    assert frame.query(
        "series_id == 'CN.PMI.MFG.HEADLINE' and reference_period == '2012-02'"
    ).iloc[0]["value"] == 51.0


def test_validation_rejects_lookahead_and_out_of_bounds_values():
    registry = load_registry(REGISTRY)
    frame = pd.DataFrame({
        "series_id": ["CN.SHIBOR.ON"],
        "reference_period": ["2026-08-25"],
        "value": [21.0],
        "source_id": ["cfets_shibor_public"],
        "release_at": ["2026-08-25T11:00:00+08:00"],
        "available_at": ["2026-08-25T10:59:00+08:00"],
        "tradable_at": ["2026-08-25T11:05:00+08:00"],
        "retrieved_at": ["2026-08-25T12:00:00+08:00"],
        "vintage_id": ["v1"],
        "raw_sha256": ["a" * 64],
    })
    report = validate_canonical(frame, registry.series_for_source("cfets_shibor_public"))
    assert not report["passed"]
    assert report["checks"]["available_not_before_release"] is False
    assert report["checks"]["values_within_registered_bounds"] is False
