from scripts.v12.run_execution_ledger_recovery_drill import run


def test_development_recovery_reconstructs_identical_immutable_state(tmp_path):
    report = run(tmp_path / "ledger.sqlite")
    assert report["status"] == "DEVELOPMENT_SQLITE_RECOVERY_DRILL_PASS"
    assert report["entry_watermark_count"] == 39
    assert report["cash"]["CNY"] == "100516.0000000000"
    assert report["positions"][0]["quantity"] == report["positions"][0]["sellable_quantity"] == 180
    assert report["positions"][0]["lots"] == 2
    assert report["paper_authority"] is False
    assert "not a PostgreSQL backup restore" in report["limitations"]
