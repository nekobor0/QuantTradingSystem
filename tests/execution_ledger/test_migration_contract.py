from pathlib import Path

import pytest

from quant_trading_system.execution_ledger.tables import metadata


ROOT = Path(__file__).parents[2]
SQL = (ROOT / "migrations" / "009_execution_ledger.sql").read_text(encoding="utf-8")
PL2_SQL = (ROOT / "migrations" / "015_execution_ledger_position_lots.sql").read_text(encoding="utf-8")
PL6_SQL = (ROOT / "migrations" / "016_execution_ledger_corporate_cash_actions.sql").read_text(encoding="utf-8")


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


@pytest.mark.parametrize("fragment", [
    "ALTER TABLE execution_ledger_entries ADD COLUMN lot_id UUID",
    "ALTER TABLE execution_ledger_entries ADD COLUMN buy_date DATE",
    "CHECK (available_at <= effective_at)",
    "UNIQUE(account_id,external_ref)",
    "ix_execution_entries_account_lot_effective",
])
def test_pl2_additive_migration_contract(fragment):
    assert fragment in PL2_SQL


def test_pl2_table_is_owned_by_metadata_and_additive_migration_only():
    assert "execution_position_adjustments" in metadata.tables
    assert "CREATE TABLE execution_position_adjustments" in PL2_SQL
    assert "execution_position_adjustments" not in SQL


@pytest.mark.parametrize("fragment", [
    "CREATE TABLE execution_corporate_cash_actions",
    "DELISTING_CASH_DISPOSAL",
    "CHECK (available_at <= effective_at)",
    "UNIQUE(account_id,external_ref)",
])
def test_pl6_corporate_cash_action_migration_contract(fragment):
    assert fragment in PL6_SQL


def test_pl6_table_is_owned_by_metadata():
    assert "execution_corporate_cash_actions" in metadata.tables
