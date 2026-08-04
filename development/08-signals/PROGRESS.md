# signals 开发进度

- 目标：把组合净目标冻结为可风控、可过期、可审批但绝非成交的人工建议。
- 顺序：输入/净额 → 整手/费用/现金 → 状态/发布 → 审批/并发 → 行动板 → 双仓储/DDL → 验收。
- 最大风险：把建议当实际持仓，或 SELL 超可卖、hard risk 仍发布。
- 任务 0：完成；上游 554 passed、signals 0，08 文档指纹一致；旧项目回测订单模型不可迁移。
- 任务 1：完成；唯一净建议、真实交易规格、整手/tick、费用、卖出释放现金和现金门禁已实现。
- 任务 2：完成；risk/对账/时效发布门禁、审批乐观锁/幂等、handoff、过期/reprice/supersede 和双策略行动板已实现。
- 任务 3：完成；内存/SQLAlchemy 双仓储、PostgreSQL DDL 与 112 项模块测试通过。
- 反向验证：临时移除 SELL settled_sellable 上限，两套仓储黄金测试均失败（exit 1）；已恢复。
- 验收：前八模块组合 666 passed、0 skipped；mypy 67 files clean；compileall、文档校验均 exit 0；受保护指纹一致。
- 状态：完成。
