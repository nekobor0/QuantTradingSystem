# platform_operations blocked items

- Docker daemon is not running and localhost PostgreSQL port 5432 is unavailable in the current environment. Live PostgreSQL migration and isolated pg_dump/restore drill cannot be claimed until an external runtime is supplied.
- The declared PostgreSQL driver `psycopg` and Python `build` frontend are not installed in the current interpreter. Dependency import smoke and wheel build cannot be completed without installing from the package index; no network installation was performed.
- Production trading API credential/backend adapters and task handlers are environment-specific injection points. The delivered container exposes fail-closed operational health; do not expose the trading API or start scheduled business workers until those adapters are supplied and integration-tested.
