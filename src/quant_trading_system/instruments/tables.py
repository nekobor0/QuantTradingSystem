"""SQLAlchemy Core table definitions for the instruments module."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
)


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

instruments = Table(
    "instruments",
    metadata,
    Column("instrument_id", Uuid(as_uuid=True), primary_key=True),
    Column("asset_type", String(64), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("board", String(32), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("name", String(256), nullable=False),
    Column("list_date", Date, nullable=False),
    Column("delist_date", Date),
    Column("lifecycle_status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("delist_date IS NULL OR delist_date >= list_date", name="listing_dates"),
)

instrument_aliases = Table(
    "instrument_aliases",
    metadata,
    Column("alias_id", Uuid(as_uuid=True), primary_key=True),
    Column("instrument_id", Uuid(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False),
    Column("source", String(64), nullable=False),
    Column("code", String(64), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="alias_validity"),
)

trading_specs = Table(
    "trading_specs",
    metadata,
    Column("spec_id", Uuid(as_uuid=True), primary_key=True),
    Column("instrument_id", Uuid(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date),
    Column("lot_size", Integer, nullable=False),
    Column("tick_size", Numeric(20, 8), nullable=False),
    Column("min_order_quantity", Integer, nullable=False),
    Column("max_order_quantity", Integer),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="spec_validity"),
    CheckConstraint("lot_size > 0", name="positive_lot_size"),
    CheckConstraint("tick_size > 0", name="positive_tick_size"),
    CheckConstraint("min_order_quantity > 0", name="positive_min_quantity"),
    CheckConstraint(
        "max_order_quantity IS NULL OR max_order_quantity >= min_order_quantity",
        name="quantity_bounds",
    ),
)

lifecycle_periods = Table(
    "instrument_lifecycle_periods",
    metadata,
    Column("period_id", Uuid(as_uuid=True), primary_key=True),
    Column("instrument_id", Uuid(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False),
    Column("status", String(16), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date),
    Column("reason", String(512), nullable=False),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="lifecycle_validity"),
)

source_records = Table(
    "instrument_source_records",
    metadata,
    Column("source_record_pk", Integer, primary_key=True, autoincrement=True),
    Column("source", String(64), nullable=False),
    Column("source_record_id", String(256), nullable=False),
    Column("revision", String(64), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("instrument_id", Uuid(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False),
    Column("batch_id", String(128), nullable=False),
    Column("raw_payload", JSON, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source", "source_record_id", "revision", name="source_record_idempotency"),
)

instrument_events = Table(
    "instrument_events",
    metadata,
    Column("event_id", Uuid(as_uuid=True), primary_key=True),
    Column("event_type", String(64), nullable=False),
    Column("instrument_id", Uuid(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
