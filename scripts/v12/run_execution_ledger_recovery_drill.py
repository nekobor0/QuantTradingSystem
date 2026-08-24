"""Development recovery drill: reconstruct the same snapshot from persisted immutable entries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.execution_ledger import (  # noqa: E402
    Account, CashEvent, CashEventType, CorporateActionType, CorporateCashAction,
    CorporateCashActionType, ExecutionLedgerService,
    FillInput, OrderInput, OrderSide, OrderSource, PositionAdjustment,
)
from quant_trading_system.execution_ledger.sqlalchemy_repository import SqlAlchemyLedgerRepository  # noqa: E402
from quant_trading_system.execution_ledger.tables import metadata  # noqa: E402



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


def run(db_path: Path) -> dict:
    if db_path.exists():
        raise RuntimeError(f"refusing to overwrite recovery drill database: {db_path}")
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    engine = create_engine(url)
    metadata.create_all(engine)
    service = ExecutionLedgerService(SqlAlchemyLedgerRepository(engine))
    t0 = datetime(2026, 8, 12, 1, 30, tzinfo=UTC)
    account = service.register_account(Account("RECOVERY_DRILL", "CNY", ("SSE",)))
    instrument = uuid4()
    service.record_cash_event(CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("100000"), t0 - timedelta(days=1), "fund", "drill"))
    fills = []
    for index, (at, price) in enumerate(((t0, "10"), (t0 + timedelta(days=2), "20"))):
        order = service.record_order(OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.BUY, 100, "CNY", at, f"buy-{index}", manual_reason="drill"))
        fills.append(service.record_fill(order.order_id, FillInput(f"fill-{index}", None, False, at, 100, Decimal(price), Decimal(), Decimal(), Decimal(), "CNY", "600000.SH", at + timedelta(days=1)), 0))
    action_at = t0 + timedelta(days=4)
    service.record_position_adjustment(PositionAdjustment(account.account_id, instrument, fills[0].fill_id, t0.date(), CorporateActionType.SPLIT, "CNY", 100, 100, Decimal(), action_at, action_at - timedelta(days=1), "split", "drill split"))
    sell = service.record_order(OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.SELL, 120, "CNY", action_at + timedelta(days=1), "sell", manual_reason="drill"))
    service.record_fill(sell.order_id, FillInput("sell-fill", None, False, action_at + timedelta(days=1), 120, Decimal("30"), Decimal("3"), Decimal("1"), Decimal(), "CNY", "600000.SH", action_at + timedelta(days=1)), 0)
    service.record_corporate_cash_action(CorporateCashAction(
        account.account_id, instrument, fills[1].fill_id, (t0 + timedelta(days=2)).date(),
        CorporateCashActionType.CASH_DIVIDEND, "CNY", Decimal("25"), Decimal("5"),
        action_at + timedelta(days=1), action_at, "dividend", "recovery drill dividend",
    ))
    delisted = uuid4()
    delist_order = service.record_order(OrderInput(account.account_id, delisted, OrderSource.MANUAL, OrderSide.BUY, 100, "CNY", t0, "delist-buy", manual_reason="drill"))
    delist_fill = service.record_fill(delist_order.order_id, FillInput("delist-fill", None, False, t0, 100, Decimal("5"), Decimal(), Decimal(), Decimal(), "CNY", "600001.SH", t0 + timedelta(days=1)), 0)
    service.record_corporate_cash_action(CorporateCashAction(
        account.account_id, delisted, delist_fill.fill_id, t0.date(), CorporateCashActionType.DELISTING_CASH_DISPOSAL,
        "CNY", Decimal("400"), Decimal(), action_at + timedelta(days=1), action_at,
        "delisting", "recovery drill delisting cash disposal",
    ))
    as_of = action_at + timedelta(days=2)
    before = service.get_account_snapshot(account.account_id, as_of, persist=False)
    engine.dispose()

    recovered_engine = create_engine(url)
    recovered = ExecutionLedgerService(SqlAlchemyLedgerRepository(recovered_engine)).get_account_snapshot(account.account_id, as_of, persist=False)
    recovered_engine.dispose()
    if before != recovered:
        # snapshot_id differs by construction; all reconstructible state must remain identical.
        comparable_before = (before.account_id, before.as_of, before.cash, before.positions, before.content_hash, before.entry_watermark, before.source)
        comparable_after = (recovered.account_id, recovered.as_of, recovered.cash, recovered.positions, recovered.content_hash, recovered.entry_watermark, recovered.source)
        if comparable_before != comparable_after:
            raise RuntimeError("recovered ledger snapshot differs from pre-close reconstruction")
    return {
        "status": "DEVELOPMENT_SQLITE_RECOVERY_DRILL_PASS",
        "database_sha256": _sha256_file(db_path),
        "account_id": str(account.account_id), "as_of": as_of.isoformat(),
        "content_hash": recovered.content_hash, "entry_watermark_count": len(recovered.entry_watermark),
        "cash": {key: str(value) for key, value in recovered.cash.items()},
        "positions": [{"instrument_id": str(p.instrument_id), "quantity": p.quantity, "sellable_quantity": p.sellable_quantity, "cost": str(p.cost), "lots": len(p.lots)} for p in recovered.positions],
        "limitations": ["SQLite development drill only", "not a PostgreSQL backup restore", "not an offline or cross-host restore"],
        "paper_authority": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise RuntimeError(f"refusing to overwrite recovery package: {out}")
    out.mkdir(parents=True, exist_ok=True)
    report = run(out / "execution_ledger_recovery.sqlite")
    _write_immutable_json(out / "recovery_report.json", report)
    manifest = {"artifact": "PL7_DEVELOPMENT_RECOVERY_DRILL_WITH_CORPORATE_CASH_ACTIONS", "implementation_sha256": _sha256_file(Path(__file__)), "files": {name: _sha256_file(out / name) for name in ("execution_ledger_recovery.sqlite", "recovery_report.json")}, "paper_authority": False}
    _write_immutable_json(out / "manifest.json", manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
