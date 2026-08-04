# fundamentals 开发进度

- 目标：实现修订不覆盖、严格 PIT 可见的基本面事实与股本变动。
- 顺序：定义/单位 → 公告质量门禁 → 修订与 PIT 查询 → 派生 → 双仓储/DDL → 验收。
- 最大风险：选择“最新版”前未先按 decision_at 过滤，造成前视偏差。
- 任务 0：完成；实测 MvpSelect 7 文件/19,310 行/7 类 schema，组合基线 135 passed，指纹一致。
- 任务 1：完成；字段定义/来源映射、公告门禁、修订并存、质量证据和修订事件已实现。
- 任务 2：完成；严格 `available_at <= decision_at`、来源策略、万元/百分比/NULL、YTD→单季、四季 TTM 与 lineage 已验证。
- 任务 3：完成；股本 PIT、内存/SQLAlchemy 双仓储和 PostgreSQL DDL 已实现。
- 反向验证：临时把 `available_at <= decision_at` 改为 `<`，两套仓储边界测试均失败（2 failed，exit 1）；已恢复。
- 验收：三模块组合 215 passed、0 skipped；mypy 26 files clean；compileall、文档校验均 exit 0。
- 状态：完成。
