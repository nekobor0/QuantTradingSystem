from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, MetaData, Numeric, String, Table, UniqueConstraint
from sqlalchemy.types import Uuid

metadata = MetaData()

accounts = Table(
    "execution_accounts", metadata,
    Column("account_id", Uuid, primary_key=True), Column("broker", String, nullable=False),
    Column("base_currency", String(3), nullable=False), Column("market_permissions", JSON, nullable=False),
    Column("status", String, nullable=False), Column("masked_number", String, nullable=False),
)
orders = Table(
    "execution_orders", metadata,
    Column("order_id", Uuid, primary_key=True), Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("instrument_id", Uuid, nullable=False), Column("source", String, nullable=False), Column("side", String, nullable=False),
    Column("quantity", Integer, nullable=False), Column("currency", String(3), nullable=False), Column("submitted_at", DateTime(timezone=True), nullable=False),
    Column("idempotency_key", String, nullable=False), Column("recommendation_id", Uuid), Column("manual_reason", String),
    Column("broker_order_id", String), Column("limit_price", Numeric), Column("status", String, nullable=False),
    Column("filled_quantity", Integer, nullable=False), Column("version", Integer, nullable=False),
    UniqueConstraint("account_id", "idempotency_key"), CheckConstraint("quantity > 0"), CheckConstraint("filled_quantity >= 0 AND filled_quantity <= quantity"),
)
fills = Table(
    "execution_fills", metadata,
    Column("fill_id", Uuid, primary_key=True), Column("order_id", Uuid, ForeignKey("execution_orders.order_id"), nullable=False),
    Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False), Column("instrument_id", Uuid, nullable=False),
    Column("broker", String, nullable=False), Column("broker_fill_id", String, nullable=False),
    Column("filled_at", DateTime(timezone=True), nullable=False), Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("quantity", Integer, nullable=False), Column("price", Numeric, nullable=False), Column("commission", Numeric, nullable=False),
    Column("tax", Numeric, nullable=False), Column("other_fee", Numeric, nullable=False), Column("currency", String(3), nullable=False),
    Column("raw_code", String, nullable=False), Column("sellable_on", DateTime(timezone=True), nullable=False),
    Column("payload_hash", String, nullable=False), Column("reverses_fill_id", Uuid, ForeignKey("execution_fills.fill_id")),
    UniqueConstraint("broker", "account_id", "broker_fill_id"), CheckConstraint("quantity > 0"), CheckConstraint("price > 0"),
)
cash_events = Table(
    "execution_cash_events", metadata,
    Column("event_id", Uuid, primary_key=True), Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("event_type", String, nullable=False), Column("currency", String(3), nullable=False), Column("amount", Numeric, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False), Column("external_ref", String, nullable=False), Column("reason", String, nullable=False),
    Column("counter_currency", String(3)), Column("source_rate", Numeric), UniqueConstraint("account_id", "external_ref"), CheckConstraint("amount <> 0"),
)
ledger_entries = Table(
    "execution_ledger_entries", metadata,
    Column("entry_id", Uuid, primary_key=True), Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("entry_type", String, nullable=False), Column("currency", String(3), nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False), Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("source_type", String, nullable=False), Column("source_id", Uuid, nullable=False), Column("instrument_id", Uuid),
    Column("quantity_delta", Integer, nullable=False), Column("cash_delta", Numeric, nullable=False), Column("cost_delta", Numeric, nullable=False),
    Column("realized_pnl_delta", Numeric, nullable=False),
)
snapshots = Table(
    "execution_account_snapshots", metadata,
    Column("snapshot_id", Uuid, primary_key=True), Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False), Column("cash", JSON, nullable=False), Column("positions", JSON, nullable=False),
    Column("content_hash", String, nullable=False), Column("entry_watermark", JSON, nullable=False), Column("source", String, nullable=False),
)
reconciliations = Table(
    "execution_reconciliations", metadata,
    Column("reconciliation_id", Uuid, primary_key=True), Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False), Column("status", String, nullable=False), Column("broker_snapshot_hash", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False), Column("resolved_at", DateTime(timezone=True)), Column("resolution_reason", String),
)
reconciliation_items = Table(
    "execution_reconciliation_items", metadata,
    Column("item_id", Uuid, primary_key=True), Column("reconciliation_id", Uuid, ForeignKey("execution_reconciliations.reconciliation_id"), nullable=False),
    Column("key", String, nullable=False), Column("system_value", Numeric, nullable=False), Column("broker_value", Numeric, nullable=False),
    Column("difference", Numeric, nullable=False), Column("material", Boolean, nullable=False), Column("resolved_reason", String),
)
statement_imports = Table(
    "execution_statement_imports", metadata,
    Column("import_id", Uuid, primary_key=True), Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("file_hash", String, nullable=False), Column("format_version", String, nullable=False), Column("preview_hash", String, nullable=False),
    Column("confirmed", Boolean, nullable=False), UniqueConstraint("account_id", "file_hash", "format_version"),
)
events = Table(
    "execution_ledger_events", metadata,
    Column("event_id", Uuid, primary_key=True), Column("event_type", String, nullable=False),
    Column("account_id", Uuid, ForeignKey("execution_accounts.account_id"), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False), Column("recorded_at", DateTime(timezone=True), nullable=False), Column("payload", JSON, nullable=False),
)
