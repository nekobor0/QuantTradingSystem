from datetime import datetime, timezone
from pathlib import Path

from quant_trading_system.research.macro_data.backfill import infer_pmi_period
from quant_trading_system.research.macro_data.contracts import capture_raw_snapshot


def test_identical_payload_deduplicates_raw_but_preserves_each_capture(tmp_path):
    common = {
        "output_root": tmp_path,
        "source_id": "official",
        "payload": b"unchanged official page",
        "request_method": "GET",
        "request_url": "https://example.test/data",
        "response_status": 200,
        "response_headers": {"Content-Type": "text/html"},
        "extension": "html",
    }
    first = capture_raw_snapshot(
        **common,
        retrieved_at=datetime(2026, 8, 25, 1, 2, 3, tzinfo=timezone.utc),
    )
    second = capture_raw_snapshot(
        **common,
        retrieved_at=datetime(2026, 8, 25, 1, 2, 4, tzinfo=timezone.utc),
    )
    assert first.raw_path == second.raw_path
    assert first.manifest_path != second.manifest_path
    assert Path(first.raw_path).read_bytes() == b"unchanged official page"
    assert Path(first.manifest_path).is_file()
    assert Path(second.manifest_path).is_file()


def test_pmi_catalog_period_inference_handles_year_boundary_and_modern_titles():
    assert infer_pmi_period("12月份全国制造业采购经理指数升势明显", "2010-01-04") == "2009-12"
    assert infer_pmi_period("2017年12月中国制造业采购经理指数为51.6%", "2017-12-31") == "2017-12"
    assert infer_pmi_period("中国制造业采购经理指数连续三个月回落", "2011-07-01") is None
