# backtest 开发进度

- 状态：完成。
- Leader 基线：上游 `801 passed`、76 个源码文件；模块规范 SHA256 `60214A0C9F4F27C63875BD4A6E153920A3244348F3F4042B0291A1C517935553`，验收后未漂移。
- 交付：冻结 Definition/Run、只读时点 Context、固定优先级事件流、双策略独立目标与 sleeve 净额、次 Bar 撮合、lot/tick/限价/停牌/无量/涨跌停/容量部分成交、版本化费用与市场规则、T+1 可卖、公司行动、Fill 驱动账户、日终 NAV、11 项指标、成本/延迟/容量敏感性、walk-forward 校验、内存/SQLAlchemy 双仓储和 PostgreSQL DDL。
- 旧系统处理：只参考费用与绩效公式；未迁移向量化主引擎、原地订单状态或可变组合。
- 模块验收：`138 passed in 1.13s`，0 failed，0 skipped。
- 十模块全量：`939 passed in 8.76s`；mypy `88 source files` 无问题；compileall 退出 0；文档校验三项 PASS。
- 反向验证：临时删除 Broker 的 `bar.market_time <= order.submitted_at` 限制后，`test_same_bar_never_fills` 非 0；恢复后模块及全量重新全绿。
- 断点续跑：下一模块从 `11-risk` Leader 实测与目标冻结开始。
