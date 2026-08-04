from pathlib import Path

import pytest

from quant_trading_system.execution_ledger.tables import metadata


ROOT = Path(__file__).parents[2]
SQL = (ROOT / "migrations" / "009_execution_ledger.sql").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", [
    "execution_accounts", "execution_orders", "execution_fills", "execution_cash_events",
    "execution_ledger_entries", "execution_account_snapshots", "execution_reconciliations",
    "execution_reconciliation_items", "execution_statement_imports", "execution_ledger_events",
])
def test_migration_and_metadata_own_required_table(name):
    assert name in SQL
    assert name in metadata.tables


@pytest.mark.parametrize("fragment", [
    "UNIQUE(account_id,idempotency_key)",
    "UNIQUE(broker,account_id,broker_fill_id)",
    "CHECK (filled_quantity >= 0 AND filled_quantity <= quantity)",
    "reverses_fill_id UUID REFERENCES execution_fills(fill_id)",
    "UNIQUE(account_id,file_hash,format_version)",
    "TIMESTAMPTZ",
    "JSONB",
])
def test_postgresql_migration_contains_integrity_contract(fragment):
    assert fragment in SQL
