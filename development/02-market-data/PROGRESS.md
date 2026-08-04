# market_data 开发进度

- 目标：实现不可变 RAW、时区正确 Bar、质量门禁、复权视图和固定 snapshot。
- 顺序：领域/时间 → instruments 解析与质量 → snapshot 查询 → 双仓储/DDL → 验收。
- 最大风险：新修订污染旧 snapshot，或来源 factor 口径含糊导致复权错误。
- 任务 0：完成；instruments 65 passed、文档校验 PASS、4 个指纹及 instruments manifest 均一致。
- 任务 1：完成；实现 UTC/本地交易日、1d/1m Bar、公司行动、市场状态、复权因子与 RAW 不可变视图。
- 任务 2：完成；实现原始文件内容寻址、失败关闭质量门禁、幂等批次、发布事件及固定 snapshot。
- 任务 3：完成；内存/SQLAlchemy 双仓储、PostgreSQL DDL、70 项模块测试和 65 项上游回归均通过。
- 反向验证：临时把 `available_at < bar_end_at` 破坏为 `<=`，既有测试按预期失败（exit 1）；已恢复。
- 验收：market_data 70 passed；instruments 65 passed；mypy 18 files clean；compileall、文档校验均 exit 0；0 skipped。
- 状态：完成。
