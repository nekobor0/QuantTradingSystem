# universe 开发进度

- 目标：实现严格 PIT、用途隔离、可解释且可冻结的证券池与分类成员关系。
- 顺序：定义/批次 → 解析与差分 → PIT 查询/解释 → 双策略快照 → 双仓储/DDL → 验收。
- 最大风险：当前名单或后到修订污染历史策略运行。
- 任务 0：完成；上游 215 passed、universe 0，指纹一致；MvpSelect 无可用历史成分源。
- 任务 1：完成；全量批次、canonical 解析、差分区间、异常变化/空池/用途门禁与质量证据已实现。
- 任务 2：完成；PIT 查询、解释、行业体系隔离、陈旧度和 ETF/个股独立快照已实现。
- 任务 3：完成；内存/SQLAlchemy 双仓储、PostgreSQL DDL 和 67 项模块测试通过。
- 反向验证：临时把 `available_at <= decision_at` 改为 `<`，两套仓储边界测试均失败（exit 1）；已恢复。
- 验收：前四模块组合 282 passed、0 skipped；mypy 34 files clean；compileall、文档校验均 exit 0；受保护指纹一致。
- 状态：完成。
