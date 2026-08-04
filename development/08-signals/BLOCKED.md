# signals 待裁决清单

- risk 与 execution_ledger 模块尚未开发，本模块先冻结它们的不可变输入契约；后续模块必须用真实事件/快照接通，不得保留伪造适配器。
- 真实 PostgreSQL 当前不可用；使用 SQLite 仓储契约与 PostgreSQL DDL 静态检查，留待 platform_operations 补 live 验收。
