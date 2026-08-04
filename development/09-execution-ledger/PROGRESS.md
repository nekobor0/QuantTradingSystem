# execution_ledger 开发进度

- 状态：完成。
- Leader 基线：上游 `666 passed`；模块规范 SHA256 `D5C3504E2922615FB5A1C43DFBADBF0E58D3500356622CBC98563862B8E1838A`，验收后未漂移。
- 交付：账户、订单状态机、真实成交、资金事件/FX、不可变账本分录、T+1 可卖、移动平均成本/已实现盈亏、时点快照、reversal、对账阻断/解除、statement 预览确认、内存与 SQLAlchemy 双仓储、PostgreSQL DDL。
- 关键边界：订单与建议不产生余额；只有 Fill/CashEvent 产生 ledger entry；重复成交幂等，超量/错币种/取消后迟到成交均不落账；更正不删除旧成交。
- 模块验收：`135 passed in 1.02s`，0 failed，0 skipped。
- 九模块全量：`801 passed in 10.23s`；mypy `76 source files` 无问题；compileall 退出 0；文档校验三项 PASS。
- 反向验证：临时删除 service 的显式 overfill 拦截后，`test_overfill_has_no_side_effect` 非 0；恢复后模块及全量重新全绿。
- 断点续跑：下一模块从 `10-backtest` Leader 实测与目标冻结开始，不改本模块已验收边界。
