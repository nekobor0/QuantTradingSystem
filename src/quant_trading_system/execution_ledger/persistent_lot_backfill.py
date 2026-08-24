"""Apply the legacy lot planner to a new SQLite copy, never to the source."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, insert, select

from .domain import LedgerEntry
from .errors import InvalidLedgerInput
from .lot_backfill import plan_legacy_lot_entries
from .sqlalchemy_repository import SqlAlchemyLedgerRepository
from .tables import accounts, fills, ledger_entries, orders


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


@dataclass(frozen=True, slots=True)
class PersistentLotBackfillResult:
    status: str
    source_sha256: str
    target_sha256: str
    account_count: int
    planned_entry_count: int
    blocked_accounts: tuple[dict[str, str], ...]


def apply_to_new_sqlite_copy(source: Path, target: Path) -> PersistentLotBackfillResult:
    """Copy source, plan every account, then append all entries atomically or none."""
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise InvalidLedgerInput("source and target database must differ")
    if not source.is_file():
        raise InvalidLedgerInput("source database does not exist")
    if target.exists():
        raise InvalidLedgerInput("target database already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_hash = _sha256(source)
    shutil.copy2(source, target)

    engine = create_engine(f"sqlite+pysqlite:///{target.as_posix()}")
    repository = SqlAlchemyLedgerRepository(engine)
    planned: list[LedgerEntry] = []
    blocked: list[dict[str, str]] = []
    try:
        with engine.connect() as connection:
            account_ids = tuple(connection.execute(select(accounts.c.account_id)).scalars())
            order_rows = connection.execute(select(orders)).mappings().all()
            fill_rows = connection.execute(select(fills)).mappings().all()
            entry_rows = connection.execute(select(ledger_entries)).mappings().all()
        all_orders = tuple(repository._order(row) for row in order_rows)
        all_fills = tuple(repository._fill(row) for row in fill_rows)
        all_entries = tuple(repository._entry(row) for row in entry_rows)
        for account_id in account_ids:
            try:
                planned.extend(plan_legacy_lot_entries(
                    account_id=account_id,
                    orders=all_orders,
                    fills=all_fills,
                    legacy_entries=all_entries,
                ))
            except InvalidLedgerInput as error:
                blocked.append({"account_id": str(account_id), "reason": str(error)})
        if blocked:
            return PersistentLotBackfillResult(
                "BLOCKED_NO_ENTRIES_WRITTEN", source_hash, _sha256(target),
                len(account_ids), len(planned), tuple(blocked),
            )
        with engine.begin() as connection:
            if planned:
                connection.execute(insert(ledger_entries), [repository._entry_values(entry) for entry in planned])
    finally:
        engine.dispose()
    if _sha256(source) != source_hash:
        raise RuntimeError("source database changed during lot backfill")
    return PersistentLotBackfillResult(
        "COMPLETE", source_hash, _sha256(target), len(account_ids), len(planned), (),
    )
