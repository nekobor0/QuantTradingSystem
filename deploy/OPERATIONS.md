# Single-host operations

Copy `.env.example` to `.env`, create the two files under `deploy/secrets/`, and keep both paths outside version control in production. Start the isolated stack with `docker compose -f deploy/compose.yaml up -d --build`. The database is not published by the base Compose file; the operations health API binds only to loopback and should sit behind a TLS reverse proxy. The trading API remains an application factory and must be wired to production backend/credential adapters before exposure.

The Windows TdxQuant bridge needs direct host access to PostgreSQL. For this local-only integration, start the database with `docker compose -f deploy/compose.yaml -f deploy/compose.tdx.yaml up -d db`. The override binds PostgreSQL only to `127.0.0.1:5432`; do not change it to `0.0.0.0`. Use the base Compose file without the override on hosts that do not run the bridge.

Apply migrations 001 through 014 in filename order before starting API/worker. Health is PASS only when database, published fresh datasets, both required strategy tasks, risk, reconciliation, outbox age, latest backup, and a recent restore drill pass. A failed primary alert remains in `ops_alert_records` as a local fallback.

Run `scripts/ops/backup.ps1` daily and `scripts/ops/restore_drill.ps1` in an isolated database at least monthly. Compare schema version, critical-table counts and backup checksum before recording a successful drill. Never restore into the production database.
