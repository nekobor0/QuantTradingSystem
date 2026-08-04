"""Command-line entry point for historical backfills and daily increments."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from quant_trading_system.instruments.errors import InstrumentError
from quant_trading_system.instruments.tables import instrument_aliases
from quant_trading_system.market_data import VolumeUnit
from quant_trading_system.market_data.errors import MarketDataError
from quant_trading_system.market_data.tables import bars

from .errors import TdxBridgeError, TdxConfigurationError
from .bulk import (
    BulkBackfillRunner,
    InstrumentBootstrapper,
    export_symbol_file,
    load_symbol_file,
    sqlalchemy_coverage_reader,
)
from .client import TdxHttpClient
from .wiring import build_bridge, open_data_layer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest TdxQuant historical daily bars")
    parser.add_argument("--database-url", default=os.environ.get("QTS_DATABASE_URL", ""))
    parser.add_argument("--endpoint", default="http://127.0.0.1:17709/")
    parser.add_argument("--raw-dir", type=Path, default=Path("artifacts/raw/tdx"))
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--volume-unit",
        choices=("shares", "lots"),
        default="shares",
        help="TdxQuant Volume unit; use lots only after source-unit verification",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backfill = commands.add_parser("backfill", help="ingest an inclusive historical date range")
    backfill.add_argument("--symbols", nargs="+", required=True)
    backfill.add_argument("--start", type=date.fromisoformat, required=True)
    backfill.add_argument("--end", type=date.fromisoformat, required=True)

    incremental = commands.add_parser("incremental", help="ingest one explicit trading date")
    incremental.add_argument("--symbols", nargs="+", required=True)
    incremental.add_argument("--date", dest="trading_date", type=date.fromisoformat, required=True)

    verify = commands.add_parser("verify", help="count persisted dates and revisions")
    verify.add_argument("--symbol", required=True)
    verify.add_argument("--start", type=date.fromisoformat, required=True)
    verify.add_argument("--end", type=date.fromisoformat, required=True)
    verify.add_argument("--expected", type=int)

    export = commands.add_parser("export-symbols", help="export a TdxQuant universe to CSV")
    export.add_argument("--markets", nargs="+", default=["5", "31"])
    export.add_argument("--output", type=Path, required=True)

    bulk = commands.add_parser("bulk-backfill", help="resumable batched historical backfill")
    bulk.add_argument("--symbols-file", type=Path, required=True)
    bulk.add_argument("--start", type=date.fromisoformat, required=True)
    bulk.add_argument("--end", type=date.fromisoformat, required=True)
    bulk.add_argument("--batch-size", type=int, default=4)
    bulk.add_argument("--workers", type=int, default=1)
    bulk.add_argument("--max-retries", type=int, default=2)
    bulk.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("artifacts/tdx_bridge/bulk_checkpoint.json"),
    )
    bulk.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/tdx_bridge/bulk_report.json"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.timeout_seconds <= 0:
            raise TdxConfigurationError("timeout must be positive")
        if args.command == "export-symbols":
            client = TdxHttpClient(args.endpoint, timeout_seconds=args.timeout_seconds)
            specs = export_symbol_file(client, args.markets, args.output)
            print(json.dumps({
                "status": "EXPORTED",
                "symbols": len(specs),
                "output": str(args.output.resolve()),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        if not args.database_url:
            raise TdxConfigurationError(
                "set QTS_DATABASE_URL or pass --database-url; credentials are never printed"
            )
        if args.command == "verify":
            return _verify(args)
        bridge, engine = build_bridge(
            args.database_url,
            args.raw_dir,
            endpoint=args.endpoint,
            timeout_seconds=args.timeout_seconds,
        )
        try:
            volume_unit = VolumeUnit.SHARES if args.volume_unit == "shares" else VolumeUnit.LOTS
            if args.command == "bulk-backfill":
                client = TdxHttpClient(args.endpoint, timeout_seconds=args.timeout_seconds)
                report = BulkBackfillRunner(
                    bridge,
                    InstrumentBootstrapper(engine, client),
                    sqlalchemy_coverage_reader(engine),
                ).run(
                    load_symbol_file(args.symbols_file),
                    start=args.start,
                    end=args.end,
                    batch_size=args.batch_size,
                    workers=args.workers,
                    max_retries=args.max_retries,
                    checkpoint_path=args.checkpoint,
                    report_path=args.report,
                    volume_unit=volume_unit,
                )
                print(json.dumps({
                    "status": "COMPLETE" if report["failed_symbols"] == 0 else "PARTIAL",
                    "requested_symbols": report["requested_symbols"],
                    "completed_symbols": report["completed_symbols"],
                    "failed_symbols": report["failed_symbols"],
                    "distinct_symbol_dates": report["distinct_symbol_dates"],
                    "rows": report["rows"],
                    "report": str(args.report.resolve()),
                    "checkpoint": str(args.checkpoint.resolve()),
                }, ensure_ascii=False, sort_keys=True))
                return 0 if report["failed_symbols"] == 0 else 3
            if args.command == "backfill":
                batch = bridge.backfill(
                    args.symbols,
                    start=args.start,
                    end=args.end,
                    volume_unit=volume_unit,
                )
            else:
                batch = bridge.incremental(
                    args.symbols,
                    trading_date=args.trading_date,
                    volume_unit=volume_unit,
                )
        finally:
            engine.dispose()
        print(json.dumps({
            "status": batch.status.value,
            "batch_id": str(batch.batch_id),
            "source": batch.source,
            "record_count": batch.record_count,
            "checksum": batch.checksum,
            "raw_uri": batch.raw_uri,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except ModuleNotFoundError as exc:
        print(f"ERROR database driver unavailable: {exc.name}", file=sys.stderr)
    except SQLAlchemyError as exc:
        print(f"ERROR database operation failed: {type(exc).__name__}", file=sys.stderr)
    except (TdxBridgeError, InstrumentError, MarketDataError, OSError, ValueError) as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
    return 2


def _verify(args: argparse.Namespace) -> int:
    engine = open_data_layer(args.database_url)
    try:
        statement = (
            select(
                func.count(func.distinct(bars.c.trading_date)),
                func.count(),
            )
            .select_from(
                bars.join(
                    instrument_aliases,
                    bars.c.instrument_id == instrument_aliases.c.instrument_id,
                )
            )
            .where(
                instrument_aliases.c.source == "tdx",
                instrument_aliases.c.code == args.symbol.strip().upper(),
                bars.c.frequency == "1d",
                bars.c.trading_date >= args.start,
                bars.c.trading_date <= args.end,
                instrument_aliases.c.valid_from <= bars.c.trading_date,
                (instrument_aliases.c.valid_to.is_(None))
                | (instrument_aliases.c.valid_to > bars.c.trading_date),
            )
        )
        with engine.connect() as connection:
            distinct_dates, rows = connection.execute(statement).one()
    finally:
        engine.dispose()
    result = {
        "symbol": args.symbol.strip().upper(),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "distinct_dates": int(distinct_dates),
        "rows": int(rows),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.expected is not None and (
        result["distinct_dates"] != args.expected or result["rows"] != args.expected
    ):
        raise TdxConfigurationError(
            f"expected {args.expected} dates and rows, got "
            f"{result['distinct_dates']} dates and {result['rows']} rows"
        )
    return 0
