CREATE TABLE execution_accounts (
  account_id UUID PRIMARY KEY, broker TEXT NOT NULL, base_currency CHAR(3) NOT NULL,
  market_permissions JSONB NOT NULL, status TEXT NOT NULL CHECK (status IN ('ACTIVE','BLOCKED_FOR_SIGNAL','DISABLED')),
  masked_number TEXT NOT NULL
);
CREATE TABLE execution_orders (
  order_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES execution_accounts(account_id), instrument_id UUID NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('RECOMMENDATION','MANUAL')), side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  quantity INTEGER NOT NULL CHECK (quantity > 0), currency CHAR(3) NOT NULL, submitted_at TIMESTAMPTZ NOT NULL,
  idempotency_key TEXT NOT NULL, recommendation_id UUID, manual_reason TEXT, broker_order_id TEXT, limit_price NUMERIC,
  status TEXT NOT NULL, filled_quantity INTEGER NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0 AND filled_quantity <= quantity),
  version INTEGER NOT NULL DEFAULT 0, UNIQUE(account_id,idempotency_key)
);
CREATE TABLE execution_fills (
  fill_id UUID PRIMARY KEY, order_id UUID NOT NULL REFERENCES execution_orders(order_id), account_id UUID NOT NULL REFERENCES execution_accounts(account_id),
  instrument_id UUID NOT NULL, broker TEXT NOT NULL, broker_fill_id TEXT NOT NULL, filled_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0), price NUMERIC NOT NULL CHECK (price > 0),
  commission NUMERIC NOT NULL CHECK (commission >= 0), tax NUMERIC NOT NULL CHECK (tax >= 0), other_fee NUMERIC NOT NULL CHECK (other_fee >= 0),
  currency CHAR(3) NOT NULL, raw_code TEXT NOT NULL, sellable_on TIMESTAMPTZ NOT NULL, payload_hash TEXT NOT NULL,
  reverses_fill_id UUID REFERENCES execution_fills(fill_id), UNIQUE(broker,account_id,broker_fill_id)
);
CREATE TABLE execution_cash_events (
  event_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES execution_accounts(account_id), event_type TEXT NOT NULL,
  currency CHAR(3) NOT NULL, amount NUMERIC NOT NULL CHECK (amount <> 0), effective_at TIMESTAMPTZ NOT NULL,
  external_ref TEXT NOT NULL, reason TEXT NOT NULL, counter_currency CHAR(3), source_rate NUMERIC,
  UNIQUE(account_id,external_ref)
);
CREATE TABLE execution_ledger_entries (
  entry_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES execution_accounts(account_id), entry_type TEXT NOT NULL,
  currency CHAR(3) NOT NULL, effective_at TIMESTAMPTZ NOT NULL, recorded_at TIMESTAMPTZ NOT NULL,
  source_type TEXT NOT NULL, source_id UUID NOT NULL, instrument_id UUID, quantity_delta INTEGER NOT NULL DEFAULT 0,
  cash_delta NUMERIC NOT NULL DEFAULT 0, cost_delta NUMERIC NOT NULL DEFAULT 0, realized_pnl_delta NUMERIC NOT NULL DEFAULT 0
);
CREATE INDEX ix_execution_entries_account_effective ON execution_ledger_entries(account_id,effective_at);
CREATE TABLE execution_account_snapshots (
  snapshot_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES execution_accounts(account_id), as_of TIMESTAMPTZ NOT NULL,
  cash JSONB NOT NULL, positions JSONB NOT NULL, content_hash TEXT NOT NULL, entry_watermark JSONB NOT NULL, source TEXT NOT NULL
);
CREATE TABLE execution_reconciliations (
  reconciliation_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES execution_accounts(account_id), as_of TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL, broker_snapshot_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, resolved_at TIMESTAMPTZ, resolution_reason TEXT
);
CREATE TABLE execution_reconciliation_items (
  item_id UUID PRIMARY KEY, reconciliation_id UUID NOT NULL REFERENCES execution_reconciliations(reconciliation_id), key TEXT NOT NULL,
  system_value NUMERIC NOT NULL, broker_value NUMERIC NOT NULL, difference NUMERIC NOT NULL, material BOOLEAN NOT NULL, resolved_reason TEXT
);
CREATE TABLE execution_statement_imports (
  import_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES execution_accounts(account_id), file_hash TEXT NOT NULL,
  format_version TEXT NOT NULL, preview_hash TEXT NOT NULL, confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(account_id,file_hash,format_version)
);
CREATE TABLE execution_ledger_events (
  event_id UUID PRIMARY KEY, event_type TEXT NOT NULL, account_id UUID NOT NULL REFERENCES execution_accounts(account_id),
  occurred_at TIMESTAMPTZ NOT NULL, recorded_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL
);
