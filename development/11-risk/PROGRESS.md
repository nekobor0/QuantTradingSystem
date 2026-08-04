# risk 开发进度

- 状态：完成。
- Leader 基线：上游 `939 passed`、88 个源码文件；模块规范 SHA256 `69B7E2B1A5F74A55F08380EE1E8C8D9ECFD55ABAA63D4ACDF6E1260D721ACF20`，验收后未漂移。
- 交付：不可变 rule/version、三 scope policy、PRE/IN_FLIGHT/POST 检查、强制对账/非负/新鲜度/过期检查、八种比较器、自定义 evaluator fail-closed、决策聚合、显式 FX、signals 决策映射、有限期双人例外、告警去重/确认/升级/解决、风险状态/袖套查询、内存/SQLAlchemy 双仓储和 PostgreSQL DDL。
- 关键边界：原始 RuleResult 永不被例外覆盖；只有有效例外参与 effective decision；POST 只接受 execution_ledger；规则异常产出 RISK_ENGINE_ERROR BLOCK。
- 模块验收：`136 passed in 3.36s`，0 failed，0 skipped。
- 十一模块全量：`1075 passed in 15.91s`；mypy `96 source files` 无问题；compileall 退出 0；文档校验三项 PASS。
- 反向验证：临时将 evaluator 异常结果改为 PASS 后，`test_evaluator_error_fails_closed_and_alerts` 非 0；恢复后模块与全量全绿。
- 断点续跑：下一模块从 `12-reporting` Leader 实测与目标冻结开始。
