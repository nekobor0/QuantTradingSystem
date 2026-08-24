from scripts.v12.run_persistent_lot_backfill_drill import run


def test_pl8_drill_is_recoverable_and_preserves_source(tmp_path):
    report = run(tmp_path / "pl8")
    assert report["status"] == "PL8_PRODUCTION_LIKE_SQLITE_COPY_BACKFILL_PASS"
    assert report["source_sha256_before"] == report["source_sha256_after"]
    assert report["account_count"] == 1 and report["planned_entry_count"] > 0
    assert report["positions"][0]["quantity"] == 900
    assert report["positions"][0]["lot_count"] == 2
    assert report["paper_authority"] is False
