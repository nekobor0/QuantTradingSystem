from datetime import datetime, timezone
from pathlib import Path

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
