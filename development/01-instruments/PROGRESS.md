# instruments 开发进度

- 目标：实现 canonical instrument_id、时点别名、生命周期、交易规格和幂等登记。
- 顺序：领域模型 → 服务规则 → 仓储端口/内存适配器 → SQLAlchemy/PostgreSQL DDL → 验收。
- 最大风险：区间边界或部分写入导致同一代码在同一时点映射多个证券。
- 任务 0：已复核 Python 3.12.7、pytest 9.1.1、文档验证三项 PASS 和三份判卷指纹。
- 状态：完成。65 passed、0 skipped，mypy/compile/docs 验证通过；半开区间 mutation 正确变红；判卷指纹与 MvpSelect 未变。真实 PostgreSQL 缺口已记 BLOCKED，待平台模块补验。
