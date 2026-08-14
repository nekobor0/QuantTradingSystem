"""Portable SQLAlchemy schema; PostgreSQL-specific constraints live in migration 002."""

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, JSON, MetaData, Numeric, String, Table, UniqueConstraint
from sqlalchemy.types import Uuid

metadata = MetaData()

dataset_batches = Table(
    "dataset_batches", metadata,
    Column("batch_id", Uuid, primary_key=True), Column("source", String(64), nullable=False),
    Column("checksum", String(128), nullable=False), Column("raw_uri", String(1024), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False), Column("status", String(16), nullable=False),
    Column("record_count", Integer, nullable=False, default=0),
    UniqueConstraint("source", "checksum", name="uq_dataset_batch_source_checksum"),
    CheckConstraint("record_count >= 0", name="ck_dataset_batch_count"),
)

bars = Table(
    "market_bars", metadata,
    Column("bar_id", Uuid, primary_key=True), Column("batch_id", Uuid, ForeignKey("dataset_batches.batch_id"), nullable=False),
    Column("instrument_id", Uuid, nullable=False), Column("frequency", String(4), nullable=False),
    Column("trading_date", Date, nullable=False), Column("bar_end_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("open", Numeric(28, 10), nullable=False), Column("high", Numeric(28, 10), nullable=False),
    Column("low", Numeric(28, 10), nullable=False), Column("close", Numeric(28, 10), nullable=False),
    Column("volume", Numeric(28, 6)), Column("turnover", Numeric(28, 6)), Column("revision", String(64), nullable=False),
    UniqueConstraint("instrument_id", "frequency", "bar_end_at", "revision", name="uq_market_bar_revision"),
    CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ck_market_bar_positive"),
    CheckConstraint("high >= open AND high >= close AND low <= open AND low <= close AND high >= low", name="ck_market_bar_envelope"),
    CheckConstraint("(volume IS NULL OR volume >= 0) AND (turnover IS NULL OR turnover >= 0)", name="ck_market_bar_nonnegative"),
)

adjustment_factors = Table(
    "adjustment_factors", metadata,
    Column("factor_id", Uuid, primary_key=True), Column("batch_id", Uuid, ForeignKey("dataset_batches.batch_id"), nullable=False),
    Column("instrument_id", Uuid, nullable=False), Column("trading_date", Date, nullable=False),
    Column("factor", Numeric(28, 12), nullable=False), Column("factor_version", String(64), nullable=False),
    Column("definition", String(256), nullable=False), Column("available_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("instrument_id", "trading_date", "factor_version", name="uq_adjustment_factor_version"),
    CheckConstraint("factor > 0", name="ck_adjustment_factor_positive"),
)

quality_results = Table(
    "data_quality_results", metadata,
    Column("result_id", Uuid, primary_key=True), Column("batch_id", Uuid, ForeignKey("dataset_batches.batch_id"), nullable=False),
    Column("rule", String(128), nullable=False), Column("severity", String(16), nullable=False),
    Column("message", String(2048), nullable=False), Column("record_index", Integer),
)

snapshots = Table(
    "dataset_snapshots", metadata,
    Column("snapshot_id", Uuid, primary_key=True), Column("content_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

snapshot_batches = Table(
    "dataset_snapshot_batches", metadata,
    Column("snapshot_id", Uuid, ForeignKey("dataset_snapshots.snapshot_id"), primary_key=True),
    Column("batch_id", Uuid, ForeignKey("dataset_batches.batch_id"), primary_key=True),
)

market_data_events = Table(
    "market_data_events", metadata,
    Column("event_id", Uuid, primary_key=True), Column("event_type", String(128), nullable=False),
    Column("batch_id", Uuid, ForeignKey("dataset_batches.batch_id"), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False), Column("payload", JSON, nullable=False),
)
