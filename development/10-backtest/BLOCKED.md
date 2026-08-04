# backtest 待补决清单

- 真实 PostgreSQL 实例当前不可用；先用 SQLite 执行仓储契约并交付 PostgreSQL DDL，live 验收留给 `platform_operations`。
- 退市处置、各券商平台费与港股通结算细则尚无业务版本；本模块要求调用方显式传入版本化规则，不硬编码臆测值。
