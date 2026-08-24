ALTER TABLE execution_ledger_entries ADD COLUMN lot_id UUID;
ALTER TABLE execution_ledger_entries ADD COLUMN buy_date DATE;

CREATE TABLE execution_position_adjustments (
  adjustment_id UUID PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES execution_accounts(account_id),
  instrument_id UUID NOT NULL,
  lot_id UUID NOT NULL,
  buy_date DATE NOT NULL,
  action_type TEXT NOT NULL CHECK (action_type IN ('SHARE_DISTRIBUTION','SPLIT','REVERSE_SPLIT','CANCELLATION','COST_BASIS_ADJUSTMENT')),
  currency CHAR(3) NOT NULL,
  quantity_delta INTEGER NOT NULL,
  sellable_quantity_delta INTEGER NOT NULL,
  cost_delta NUMERIC NOT NULL,
  effective_at TIMESTAMPTZ NOT NULL,
  available_at TIMESTAMPTZ NOT NULL,
  external_ref TEXT NOT NULL,
  reason TEXT NOT NULL,
  CHECK (available_at <= effective_at),
  CHECK (quantity_delta <> 0 OR sellable_quantity_delta <> 0 OR cost_delta <> 0),
  UNIQUE(account_id,external_ref)
);

CREATE INDEX ix_execution_entries_account_lot_effective
  ON execution_ledger_entries(account_id,lot_id,effective_at);
