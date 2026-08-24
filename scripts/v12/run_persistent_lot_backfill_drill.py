"""PL8 drill: backfill a persisted legacy SQLite database into a new copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, delete

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.execution_ledger import (  # noqa: E402
    Account, CashEvent, CashEventType, EntryType, ExecutionLedgerService,
    FillInput, OrderInput, OrderSide, OrderSource,
)
from quant_trading_system.execution_ledger.persistent_lot_backfill import apply_to_new_sqlite_copy  # noqa: E402
from quant_trading_system.execution_ledger.sqlalchemy_repository import SqlAlchemyLedgerRepository  # noqa: E402
from quant_trading_system.execution_ledger.tables import ledger_entries, metadata  # noqa: E402



UTC = timezone.utc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write_immutable_json(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _build_legacy_source(path: Path) -> tuple[object, datetime]:
    engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    metadata.create_all(engine)
    service = ExecutionLedgerService(SqlAlchemyLedgerRepository(engine))
    t0 = datetime(2026, 8, 1, 8, tzinfo=UTC)
    account = service.register_account(Account("PL8_PRODUCTION_LIKE", "CNY", ("SSE", "SZSE")))
    service.record_cash_event(CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("1000000"), t0 - timedelta(days=1), "fund", "PL8 fixture"))
    instrument = uuid4()
    for index, (at, price, quantity) in enumerate(((t0, "10", 1000), (t0 + timedelta(days=2), "12", 500))):
        order = service.record_order(OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.BUY, quantity, "CNY", at, f"buy-{index}", manual_reason="PL8 fixture"))
        service.record_fill(order.order_id, FillInput(f"fill-{index}", None, False, at, quantity, Decimal(price), Decimal("5"), Decimal(), Decimal(), "CNY", "600000.SH", at + timedelta(days=1)), 0)
    sell_at = t0 + timedelta(days=5)
    sell = service.record_order(OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.SELL, 600, "CNY", sell_at, "sell", manual_reason="PL8 fixture"))
    service.record_fill(sell.order_id, FillInput("sell-fill", None, False, sell_at, 600, Decimal("15"), Decimal("5"), Decimal("9"), Decimal(), "CNY", "600000.SH", sell_at), 0)
    with engine.begin() as connection:
        connection.execute(delete(ledger_entries).where(ledger_entries.c.entry_type.in_([EntryType.LOT_POSITION.value, EntryType.LOT_SETTLEMENT.value])))
    engine.dispose()
    return account.account_id, sell_at + timedelta(days=1)


def run(output: Path) -> dict:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing to overwrite PL8 drill output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source = output / "legacy_source_read_only.sqlite"
    target = output / "lot_backfilled_target.sqlite"
    account_id, as_of = _build_legacy_source(source)
    source_before = _sha256_file(source)
    result = apply_to_new_sqlite_copy(source, target)
    source_after = _sha256_file(source)
    if result.status != "COMPLETE" or source_before != source_after:
        raise RuntimeError("PL8 copy backfill did not complete with an unchanged source")
    engine = create_engine(f"sqlite+pysqlite:///{target.as_posix()}")
    snapshot = ExecutionLedgerService(SqlAlchemyLedgerRepository(engine)).get_account_snapshot(account_id, as_of, persist=False)
    engine.dispose()
    report = {
        "status": "PL8_PRODUCTION_LIKE_SQLITE_COPY_BACKFILL_PASS",
        "source_sha256_before": source_before,
        "source_sha256_after": source_after,
        "target_sha256": _sha256_file(target),
        "account_count": result.account_count,
        "planned_entry_count": result.planned_entry_count,
        "blocked_accounts": list(result.blocked_accounts),
        "recovered_content_hash": snapshot.content_hash,
        "entry_watermark_count": len(snapshot.entry_watermark),
        "cash": {currency: str(amount) for currency, amount in snapshot.cash.items()},
        "positions": [{
            "instrument_id": str(position.instrument_id), "quantity": position.quantity,
            "sellable_quantity": position.sellable_quantity, "cost": str(position.cost),
            "lot_count": len(position.lots),
        } for position in snapshot.positions],
        "limitations": [
            "production-like SQLite copy drill only",
            "not a PostgreSQL backup restore",
            "not a cross-host or offline restore",
            "paper/live/QMT authority remains false",
        ],
        "paper_authority": False,
    }
    _write_immutable_json(output / "backfill_report.json", report)
    manifest = {
        "artifact": "PL8_PRODUCTION_LIKE_SQLITE_COPY_LOT_BACKFILL",
        "implementation_sha256": _sha256_file(Path(__file__)),
        "library_sha256": _sha256_file(ROOT / "src/quant_trading_system/execution_ledger/persistent_lot_backfill.py"),
        "files": {name: _sha256_file(output / name) for name in (
            "legacy_source_read_only.sqlite", "lot_backfilled_target.sqlite", "backfill_report.json",
        )},
        "paper_authority": False,
    }
    _write_immutable_json(output / "manifest.json", manifest)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
