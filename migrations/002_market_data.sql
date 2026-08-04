-- Immutable market-data facts and snapshot membership (PostgreSQL 15+).
CREATE TABLE dataset_batches (
    batch_id uuid PRIMARY KEY, source text NOT NULL, checksum text NOT NULL,
    raw_uri text NOT NULL, received_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('RECEIVED','REJECTED','PUBLISHED')),
    record_count integer NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    UNIQUE (source, checksum)
);
CREATE TABLE trading_sessions (
    exchange text NOT NULL, trading_date date NOT NULL, opens_at timestamptz NOT NULL,
    closes_at timestamptz NOT NULL, is_open boolean NOT NULL, PRIMARY KEY(exchange,trading_date),
    CHECK (closes_at > opens_at)
);
CREATE TABLE market_bars (
    bar_id uuid PRIMARY KEY, batch_id uuid NOT NULL REFERENCES dataset_batches,
    instrument_id uuid NOT NULL REFERENCES instruments, frequency text NOT NULL CHECK (frequency IN ('1d','1m')),
    trading_date date NOT NULL, bar_end_at timestamptz NOT NULL, available_at timestamptz NOT NULL,
    open numeric(28,10) NOT NULL, high numeric(28,10) NOT NULL, low numeric(28,10) NOT NULL, close numeric(28,10) NOT NULL,
    volume numeric(28,6), turnover numeric(28,6), revision text NOT NULL,
    UNIQUE(instrument_id,frequency,bar_end_at,revision),
    CHECK (open>0 AND high>0 AND low>0 AND close>0),
    CHECK (high>=open AND high>=close AND low<=open AND low<=close AND high>=low),
    CHECK ((volume IS NULL OR volume>=0) AND (turnover IS NULL OR turnover>=0)),
    CHECK (available_at>=bar_end_at)
);
CREATE TABLE corporate_actions (
    action_id uuid PRIMARY KEY, batch_id uuid NOT NULL REFERENCES dataset_batches,
    instrument_id uuid NOT NULL REFERENCES instruments, action_type text NOT NULL,
    ex_date date NOT NULL, announced_at timestamptz NOT NULL, available_at timestamptz NOT NULL,
    source text NOT NULL, revision text NOT NULL, cash_amount numeric(28,10), ratio numeric(28,12), pay_date date,
    CHECK (available_at>=announced_at), UNIQUE(instrument_id,action_type,ex_date,source,revision)
);
CREATE TABLE adjustment_factors (
    factor_id uuid PRIMARY KEY, batch_id uuid NOT NULL REFERENCES dataset_batches,
    instrument_id uuid NOT NULL REFERENCES instruments, trading_date date NOT NULL,
    factor numeric(28,12) NOT NULL CHECK(factor>0), factor_version text NOT NULL,
    definition text NOT NULL, available_at timestamptz NOT NULL,
    UNIQUE(instrument_id,trading_date,factor_version)
);
CREATE TABLE market_statuses (
    status_id uuid PRIMARY KEY, batch_id uuid NOT NULL REFERENCES dataset_batches,
    instrument_id uuid NOT NULL REFERENCES instruments, trading_date date NOT NULL,
    status text NOT NULL, available_at timestamptz NOT NULL, reason text NOT NULL DEFAULT '',
    UNIQUE(instrument_id,trading_date,status,batch_id)
);
CREATE TABLE data_quality_results (
    result_id uuid PRIMARY KEY, batch_id uuid NOT NULL REFERENCES dataset_batches,
    rule text NOT NULL, severity text NOT NULL CHECK(severity IN ('WARNING','ERROR')),
    message text NOT NULL, record_index integer
);
CREATE TABLE dataset_snapshots (
    snapshot_id uuid PRIMARY KEY, content_hash char(64) NOT NULL, created_at timestamptz NOT NULL
);
CREATE TABLE dataset_snapshot_batches (
    snapshot_id uuid NOT NULL REFERENCES dataset_snapshots,
    batch_id uuid NOT NULL REFERENCES dataset_batches, PRIMARY KEY(snapshot_id,batch_id)
);
CREATE TABLE market_data_events (
    event_id uuid PRIMARY KEY, event_type text NOT NULL, batch_id uuid NOT NULL REFERENCES dataset_batches,
    occurred_at timestamptz NOT NULL, payload jsonb NOT NULL
);
