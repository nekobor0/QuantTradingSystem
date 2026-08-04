BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE instruments (
    instrument_id uuid PRIMARY KEY,
    asset_type varchar(64) NOT NULL,
    exchange varchar(16) NOT NULL,
    board varchar(32) NOT NULL,
    currency char(3) NOT NULL,
    name varchar(256) NOT NULL,
    list_date date NOT NULL,
    delist_date date,
    lifecycle_status varchar(16) NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT ck_instruments_listing_dates CHECK (delist_date IS NULL OR delist_date >= list_date)
);

CREATE TABLE instrument_aliases (
    alias_id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES instruments(instrument_id),
    source varchar(64) NOT NULL,
    code varchar(64) NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    CONSTRAINT ck_instrument_aliases_validity CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ex_instrument_aliases_no_overlap EXCLUDE USING gist (
        source WITH =,
        code WITH =,
        daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
    )
);

CREATE INDEX ix_instrument_aliases_instrument_id ON instrument_aliases(instrument_id);

CREATE TABLE trading_specs (
    spec_id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES instruments(instrument_id),
    valid_from date NOT NULL,
    valid_to date,
    lot_size integer NOT NULL CHECK (lot_size > 0),
    tick_size numeric(20, 8) NOT NULL CHECK (tick_size > 0),
    min_order_quantity integer NOT NULL CHECK (min_order_quantity > 0),
    max_order_quantity integer,
    CONSTRAINT ck_trading_specs_validity CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_trading_specs_quantity CHECK (
        max_order_quantity IS NULL OR max_order_quantity >= min_order_quantity
    ),
    CONSTRAINT ex_trading_specs_no_overlap EXCLUDE USING gist (
        instrument_id WITH =,
        daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
    )
);

CREATE TABLE instrument_lifecycle_periods (
    period_id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES instruments(instrument_id),
    status varchar(16) NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    reason varchar(512) NOT NULL,
    CONSTRAINT ck_instrument_lifecycle_validity CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ex_instrument_lifecycle_no_overlap EXCLUDE USING gist (
        instrument_id WITH =,
        daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
    )
);

CREATE TABLE instrument_source_records (
    source_record_pk bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source varchar(64) NOT NULL,
    source_record_id varchar(256) NOT NULL,
    revision varchar(64) NOT NULL,
    payload_hash char(64) NOT NULL,
    instrument_id uuid NOT NULL REFERENCES instruments(instrument_id),
    batch_id varchar(128) NOT NULL,
    raw_payload jsonb NOT NULL,
    recorded_at timestamptz NOT NULL,
    CONSTRAINT uq_instrument_source_record UNIQUE (source, source_record_id, revision)
);

CREATE TABLE instrument_events (
    event_id uuid PRIMARY KEY,
    event_type varchar(64) NOT NULL,
    instrument_id uuid NOT NULL REFERENCES instruments(instrument_id),
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);

COMMIT;
