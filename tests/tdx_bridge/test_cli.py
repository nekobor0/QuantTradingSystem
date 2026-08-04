from quant_trading_system.tdx_bridge.cli import build_parser, main


def test_cli_parses_backfill_contract() -> None:
    args = build_parser().parse_args([
        "backfill", "--symbols", "600000.SH", "--start", "2024-01-01", "--end", "2024-01-31"
    ])
    assert args.command == "backfill"
    assert args.symbols == ["600000.SH"]
    assert args.volume_unit == "shares"


def test_cli_fails_closed_without_database_url(monkeypatch, capsys) -> None:
    monkeypatch.delenv("QTS_DATABASE_URL", raising=False)
    result = main([
        "backfill", "--symbols", "600000.SH", "--start", "2024-01-01", "--end", "2024-01-31"
    ])
    assert result == 2
    assert "QTS_DATABASE_URL" in capsys.readouterr().err


def test_cli_parses_bulk_contract() -> None:
    args = build_parser().parse_args([
        "bulk-backfill", "--symbols-file", "symbols.csv",
        "--start", "2005-01-01", "--end", "2026-07-28",
    ])
    assert args.command == "bulk-backfill"
    assert args.batch_size == 4
    assert args.workers == 1
    assert args.max_retries == 2
