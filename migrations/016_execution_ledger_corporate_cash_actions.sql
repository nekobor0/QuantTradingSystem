CREATE TABLE execution_corporate_cash_actions (
  action_id UUID PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES execution_accounts(account_id),
  instrument_id UUID NOT NULL,
  lot_id UUID NOT NULL,
  buy_date DATE NOT NULL,
  action_type TEXT NOT NULL CHECK (action_type IN ('CASH_DIVIDEND','DELISTING_CASH_DISPOSAL')),
  currency CHAR(3) NOT NULL,
  gross_cash NUMERIC NOT NULL CHECK (gross_cash > 0),
  withholding_tax NUMERIC NOT NULL CHECK (withholding_tax >= 0 AND withholding_tax < gross_cash),
  effective_at TIMESTAMPTZ NOT NULL,
  available_at TIMESTAMPTZ NOT NULL,
  external_ref TEXT NOT NULL,
  reason TEXT NOT NULL,
  CHECK (available_at <= effective_at),
  UNIQUE(account_id,external_ref)
);

CREATE INDEX ix_execution_corporate_cash_actions_account_effective
  ON execution_corporate_cash_actions(account_id,effective_at);
