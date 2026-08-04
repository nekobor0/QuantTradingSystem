# TDX bridge blocked items

- 2026-07-28: the TQ source prerequisite is resolved and live data extraction passes.
- Production PostgreSQL connectivity is resolved: loopback-only Compose override, migrations 001-014, project `.venv`, and real TQ persistence pass.
- Current TDX A-share/ETF lists are not historical membership lists and cannot supply delisted securities absent from the client list; a separate historical master source remains required to close survivorship bias.
- Automatic ETF domestic/overseas classification is heuristic when the TDX underlying-market fields are empty; manifest overrides are supported and should be reviewed before strategy use.
