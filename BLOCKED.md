# External verification and production integration gaps

- Docker, loopback PostgreSQL, migrations 001-014, and `psycopg` are now verified. Backup and isolated restore drill remain unverified.
- Production credential verification, trading-backend adapters, data-provider credentials, alert destinations, TLS proxy, broker formats, and scheduled task handlers must be supplied and integration-tested before paper/live use.
- No purchased tick feed or broker direct execution is included. Execution remains manual as designed.
- TdxQuant source connectivity and production PostgreSQL persistence now pass. The exported 7,198-symbol universe is the client's current A-share plus ETF list; it does not prove historical delisted-security coverage, so survivorship-bias remediation still needs a separate historical master source.
- `ETF_AUTO` uses a documented name-keyword heuristic because TDX stock info did not return a reliable underlying-market field in live samples. Review or override ETF asset types in the manifest before using that classification as a strategy filter.
