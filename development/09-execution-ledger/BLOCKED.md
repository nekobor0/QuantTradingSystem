# execution_ledger 待补决清单

- 券商真实 statement 格式尚未提供；本模块只冻结幂等预览/确认契约，不臆造券商列映射。
- 当前环境无可用 PostgreSQL 实例；已用 SQLite 验证 SQLAlchemy 仓储契约并静态交付 PostgreSQL DDL，真实 PostgreSQL 事务/类型验收留给 `platform_operations`。
