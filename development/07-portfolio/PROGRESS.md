# portfolio 开发进度

- 目标：把 ETF/个股两个 sleeve 合成纯多头、现金明确、约束可解释的连续目标。
- 顺序：输入/预算 → 重叠合并 → 冻结仓位 → 固定顺序约束 → delta/解释 → 双仓储/DDL → 验收。
- 最大风险：把目标误当实际持仓，或缺一策略时静默降级。
- 任务 0：完成；上游 468 passed、portfolio 0，07 文档指纹一致；旧项目无可复用的双 sleeve 实盘组合器。
- 任务 1：完成；双 required sleeve、预算现金、重叠证券合并和全现金组合已实现。
- 任务 2：完成；冻结实际仓位、单标的/市场/行业/换手/min cash 固定顺序约束、贡献与 delta 解释已实现。
- 任务 3：完成；内存/SQLAlchemy 双仓储、PostgreSQL DDL 与 86 项模块测试通过。
- 反向验证：临时放宽策略负权重门禁，既有边界测试失败（exit 1）；已恢复。
- 验收：前七模块组合 554 passed、0 skipped；mypy 59 files clean；compileall、文档校验均 exit 0；受保护指纹一致。
- 状态：完成。
