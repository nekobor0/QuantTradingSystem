# Local data management

Market data, research inputs, order and account exports, databases, logs, backtest results, caches, model files, and generated artifacts stay outside Git.

- Existing research data and generated outputs remain under local `artifacts/`; only reviewed preregistration Markdown in `artifacts/registrations/` is versioned.
- New raw or downloaded data belongs in one of the ignored local directories such as `data/`, `downloads/`, or `artifacts/`.
- Rebuild data with the checked-in scripts and document the provider, date range, schema, and checksum without copying data samples into documentation.
- Configure paths and credentials through ignored local environment files or the operating system secret store. Start from `.env.example`, which contains invalid examples only.
- A new machine must recreate its local data directories, install dependencies, configure local paths, and run the relevant downloader or migration. GitHub is not a data backup.

Never put real API keys, account identifiers, orders, fills, positions, cookies, database snapshots, or credential-bearing logs in this document or elsewhere in Git.
