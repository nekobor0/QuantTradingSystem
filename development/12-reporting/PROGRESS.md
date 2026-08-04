# reporting 开发进度

- 状态：完成。
- Leader 基线：上游 `1075 passed`、96 个源码文件；模块规范 SHA256 `55A74E31403DBC633BA2D43A8FF41A14521DCADDD27424015EC66F44A3FE5AD4`，验收后未漂移。
- 交付：四种模式报告定义、冻结输入、NAV/成交 canonical model、收益/回撤/换手/费用/FX 指标、双策略+CROSS_CONSTRAINT+CASH 四维归因、ETF/个股运营摘要、12 项质量闸门、确定性 HTML/CSV/chart artifact、ExplainMetric、脱敏/escape/hash 校验、内存/SQLAlchemy 双仓储与 PostgreSQL DDL。
- 关键边界：LIVE 只接受已对账 execution_ledger；未成交建议不进入指标；表格/图表/HTML 只消费同一 ReportMetric；质量失败只能 INCOMPLETE 且 artifact 不可发布。
- 模块验收：`122 passed in 0.67s`，0 failed，0 skipped。
- 十二模块全量：`1197 passed in 10.08s`；mypy `104 source files` 无问题；compileall 退出 0；文档校验三项 PASS。
- 反向验证：临时令 LIVE 对账检查恒真后，`test_unreconciled_live_is_incomplete_and_unpublishable` 非 0；恢复后模块与全量全绿。
- 断点续跑：下一模块从 `13-api-ui` Leader 实测与目标冻结开始。
