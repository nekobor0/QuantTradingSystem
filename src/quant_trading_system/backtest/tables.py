from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, MetaData, Numeric, String, Table, UniqueConstraint
from sqlalchemy.types import Uuid

metadata = MetaData()
definitions = Table("backtest_definitions", metadata,
    Column("definition_id", Uuid, primary_key=True), Column("name", String, nullable=False), Column("strategies", JSON, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False), Column("end_at", DateTime(timezone=True), nullable=False),
    Column("initial_cash", Numeric, nullable=False), Column("base_currency", String(3), nullable=False), Column("data_snapshot_id", Uuid, nullable=False),
    Column("universe_snapshot_id", Uuid, nullable=False), Column("code_version", String, nullable=False), Column("random_seed", Integer, nullable=False),
    Column("max_participation", Numeric, nullable=False), Column("execution_delay_bars", Integer, nullable=False), Column("benchmark_id", Uuid),
    Column("delisting_policy", String, nullable=False), CheckConstraint("initial_cash > 0"), CheckConstraint("execution_delay_bars >= 1"))
runs = Table("backtest_runs", metadata,
    Column("run_id", Uuid, primary_key=True), Column("definition_id", Uuid, ForeignKey("backtest_definitions.definition_id"), nullable=False),
    Column("input_hash", String, unique=True, nullable=False), Column("result_hash", String), Column("status", String, nullable=False),
    Column("started_at", DateTime(timezone=True)), Column("completed_at", DateTime(timezone=True)), Column("last_sequence", Integer, nullable=False), Column("error", String))
events = Table("backtest_simulation_events", metadata,
    Column("event_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False),
    Column("sequence", Integer, nullable=False), Column("market_time", DateTime(timezone=True), nullable=False), Column("received_at", DateTime(timezone=True), nullable=False),
    Column("priority", Integer, nullable=False), Column("event_type", String, nullable=False), Column("payload_version", String, nullable=False), Column("payload", JSON, nullable=False),
    Column("causation_id", Uuid), Column("correlation_id", Uuid), UniqueConstraint("run_id", "sequence"))
orders = Table("backtest_sim_orders", metadata,
    Column("order_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("instrument_id", Uuid, nullable=False),
    Column("market", String, nullable=False), Column("side", String, nullable=False), Column("order_type", String, nullable=False), Column("quantity", Integer, nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False), Column("eligible_after_bar_sequence", Integer, nullable=False), Column("limit_price", Numeric),
    Column("filled_quantity", Integer, nullable=False), Column("status", String, nullable=False), Column("reason", String), CheckConstraint("quantity > 0"))
fills = Table("backtest_sim_fills", metadata,
    Column("fill_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("order_id", Uuid, ForeignKey("backtest_sim_orders.order_id"), nullable=False),
    Column("instrument_id", Uuid, nullable=False), Column("side", String, nullable=False), Column("quantity", Integer, nullable=False), Column("price", Numeric, nullable=False),
    Column("gross", Numeric, nullable=False), Column("commission", Numeric, nullable=False), Column("tax", Numeric, nullable=False), Column("platform_fee", Numeric, nullable=False),
    Column("slippage_cost", Numeric, nullable=False), Column("filled_at", DateTime(timezone=True), nullable=False), Column("bar_id", Uuid, nullable=False))
ledger = Table("backtest_sim_ledger", metadata,
    Column("entry_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("kind", String, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False), Column("source_id", Uuid, nullable=False), Column("cash_delta", Numeric, nullable=False),
    Column("instrument_id", Uuid), Column("quantity_delta", Integer, nullable=False), Column("fee_delta", Numeric, nullable=False))
snapshots = Table("backtest_snapshots", metadata,
    Column("snapshot_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("as_of", DateTime(timezone=True), nullable=False),
    Column("cash", Numeric, nullable=False), Column("positions", JSON, nullable=False), Column("nav", Numeric, nullable=False), Column("sleeve_exposure", JSON, nullable=False), Column("content_hash", String, nullable=False))
metrics = Table("backtest_metrics", metadata,
    Column("metric_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("name", String, nullable=False),
    Column("value", Numeric), Column("unit", String, nullable=False), Column("scope", String, nullable=False), UniqueConstraint("run_id", "name", "scope"))
artifacts = Table("backtest_artifacts", metadata,
    Column("artifact_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("artifact_type", String, nullable=False),
    Column("content_hash", String, nullable=False), Column("reference", String, nullable=False))
contributions = Table("backtest_sleeve_contributions", metadata,
    Column("contribution_id", Uuid, primary_key=True), Column("run_id", Uuid, ForeignKey("backtest_runs.run_id"), nullable=False), Column("strategy_run_id", Uuid, nullable=False),
    Column("kind", String, nullable=False), Column("instrument_id", Uuid, nullable=False), Column("raw_weight", Numeric, nullable=False), Column("final_weight", Numeric, nullable=False))

