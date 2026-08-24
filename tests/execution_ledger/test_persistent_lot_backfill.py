import hashlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, delete

from quant_trading_system.execution_ledger import Account, CashEvent, CashEventType, EntryType, ExecutionLedgerService, OrderSide
from quant_trading_system.execution_ledger.persistent_lot_backfill import apply_to_new_sqlite_copy
from quant_trading_system.execution_ledger.sqlalchemy_repository import SqlAlchemyLedgerRepository
from quant_trading_system.execution_ledger.tables import ledger_entries, metadata


from .conftest import T0, fill, manual_order


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _legacy_source(path: Path, *, ambiguous: bool = False):
    engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    metadata.create_all(engine)
    repository = SqlAlchemyLedgerRepository(engine)
    service = ExecutionLedgerService(repository)
    account = service.register_account(Account("production-like", "CNY", ("SSE",)))
    service.record_cash_event(CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("100000"), T0, "fund", "fixture"))
    instrument = __import__("uuid").uuid4()
    buy = service.record_order(manual_order(account, instrument, key="buy"))
    recorded = service.record_fill(buy.order_id, fill(fill_id="buy", settle_days=0, commission="0"), 0)
    sell_at = T0 + timedelta(days=2)
    sell = service.record_order(manual_order(account, instrument, side=OrderSide.SELL, quantity=40, key="sell", at=sell_at))
    service.record_fill(sell.order_id, fill(fill_id="sell", quantity=40, price="12", commission="0", at=sell_at, settle_days=0), 0)
    with engine.begin() as connection:
        connection.execute(delete(ledger_entries).where(ledger_entries.c.entry_type.in_([EntryType.LOT_POSITION.value, EntryType.LOT_SETTLEMENT.value])))
        if ambiguous:
            aggregate = repository.entries(account.account_id)[0]
            connection.execute(ledger_entries.insert().values(**repository._entry_values(replace(
                aggregate, entry_id=__import__("uuid").uuid4(), source_type="CORPORATE_ACTION",
            ))))
    engine.dispose()
    return account.account_id, instrument, sell_at


def _legacy_aggregate(repository, account_id, instrument_id, as_of):
    entries = tuple(entry for entry in repository.entries(account_id) if entry.effective_at <= as_of)
    cash = sum((entry.cash_delta for entry in entries if entry.entry_type is EntryType.CASH), Decimal())
    quantity = sum(entry.quantity_delta for entry in entries if entry.entry_type is EntryType.POSITION and entry.instrument_id == instrument_id)
    sellable = sum(entry.quantity_delta for entry in entries if entry.entry_type is EntryType.SETTLEMENT and entry.instrument_id == instrument_id)
    cost = sum((entry.cost_delta for entry in entries if entry.entry_type is EntryType.POSITION and entry.instrument_id == instrument_id), Decimal())
    return cash, quantity, sellable, cost


def test_persistent_backfill_copies_source_appends_atomically_and_recovers(tmp_path: Path):
    source = tmp_path / "source.sqlite"; target = tmp_path / "target.sqlite"
    account_id, instrument_id, as_of = _legacy_source(source)
    source_hash = _sha256_file(source)
    source_repo = SqlAlchemyLedgerRepository(create_engine(f"sqlite+pysqlite:///{source.as_posix()}"))
    before = _legacy_aggregate(source_repo, account_id, instrument_id, as_of)

    result = apply_to_new_sqlite_copy(source, target)
    assert result.status == "COMPLETE" and result.planned_entry_count > 0
    assert _sha256_file(source) == source_hash == result.source_sha256
    recovered = ExecutionLedgerService(SqlAlchemyLedgerRepository(create_engine(f"sqlite+pysqlite:///{target.as_posix()}")))
    snapshot = recovered.get_account_snapshot(account_id, as_of, persist=False)
    position = snapshot.positions[0]
    assert (snapshot.cash["CNY"], position.quantity, position.sellable_quantity, position.cost) == before
    assert len(position.lots) == 1


def test_persistent_backfill_blocks_all_writes_on_corporate_action_ambiguity(tmp_path: Path):
    source = tmp_path / "source.sqlite"; target = tmp_path / "target.sqlite"
    account_id, _, _ = _legacy_source(source, ambiguous=True)
    result = apply_to_new_sqlite_copy(source, target)
    assert result.status == "BLOCKED_NO_ENTRIES_WRITTEN"
    assert result.blocked_accounts[0]["account_id"] == str(account_id)
    engine = create_engine(f"sqlite+pysqlite:///{target.as_posix()}")
    repo = SqlAlchemyLedgerRepository(engine)
    assert not any(entry.entry_type in (EntryType.LOT_POSITION, EntryType.LOT_SETTLEMENT) for entry in repo.entries(account_id))


def test_persistent_backfill_refuses_source_overwrite_and_existing_target(tmp_path: Path):
    source = tmp_path / "source.sqlite"; _legacy_source(source)
    try:
        apply_to_new_sqlite_copy(source, source)
        raise AssertionError("same path must fail")
    except Exception as error:
        assert "must differ" in str(error)
    target = tmp_path / "target.sqlite"; target.write_bytes(b"occupied")
    try:
        apply_to_new_sqlite_copy(source, target)
        raise AssertionError("existing target must fail")
    except Exception as error:
        assert "already exists" in str(error)
