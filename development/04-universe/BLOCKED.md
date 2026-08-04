# universe 待裁决清单

- MvpSelect 未保存可直接用于生产的港股通/指数历史成分时间序列；本模块实现接入契约和质量门禁，不伪造历史数据。
- 真实 PostgreSQL 当前不可用；使用 SQLite 仓储契约和 PostgreSQL DDL 静态检查，留待 platform_operations 补 live 验收。
