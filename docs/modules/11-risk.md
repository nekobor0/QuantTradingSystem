# 11 风控模块

## 目标与边界

用版本化规则对数据、目标组合、建议订单、实际账户和运行状态做事前/事中/事后检查，输出 hard block、需审批或 warning，并确保违规能被发现和追踪。

本模块不修改策略分数、目标组合或成交事实；例外通过单独审批记录，不覆盖原检查结果。

## 所有数据

- `risk_rule` / `risk_rule_version`：适用对象、表达式、阈值、严重级别、生效区间和 owner。
- `risk_policy`：账户/策略/市场绑定的规则集合。
- `risk_scope`：规则适用于 `ETF_TIMING` sleeve、`EQUITY_DAILY_SELECTION` sleeve 或 `COMBINED_ACCOUNT`，聚合结果不替代分项结果。
- `risk_check_run` / `risk_check_result`：输入快照、规则版本、观测值、阈值、结果和解释；证券对象只使用 `instrument_id`。
- `risk_exception`：申请、批准人、理由、范围、失效时间和状态。
- `risk_alert`：告警去重键、状态、确认、升级和解决证据。

检查结果不可变；规则修改形成新版本。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `RunPreTradeChecks(target_or_signal_id, account_snapshot_id, policy_version)` | 返回总体决策和逐规则结果 |
| Command | `RunPostTradeChecks(account_snapshot_id, market_snapshot_id, policy_version)` | 评估实际而非建议暴露 |
| Command | `ApproveException(result_id, scope, expires_at, reason)` | hard block 默认不可豁免；可豁免范围由规则定义 |
| Query | `GetRiskState(account_id, as_of)` | 返回 active breach、陈旧检查和阻断原因 |
| Query | `GetSleeveRisk(target_portfolio_id)` | 返回 ETF、个股与合并组合三层检查及贡献 |
| Event | `RiskBreachDetected` / `RiskBreachResolved` | 告警以规则、对象、观察窗口去重 |

## 主流程与状态

冻结检查输入 → 选择时点有效 policy → 先检查两个 sleeve，再检查合并目标/账户 → 聚合 `BLOCK > APPROVAL_REQUIRED > WARNING > PASS` → 生成告警/阻断 → 用户确认或审批例外 → 新快照重检后解决。旧结果不得因规则更新自动变绿。

## 业务规则

- 事前至少覆盖现金、负持仓、单标的/行业/市场、持仓数、流动性、资格、停牌/涨跌停、整手和数据/账户陈旧。
- 事中覆盖信号过期、价格偏离、部分成交、未执行和超量成交。
- 事后覆盖实际暴露、现金、回撤、换手、成本、币种、对账和数据/任务健康。
- hard block 失败时 signals 禁止发布；账户未对账属于 hard block。
- 阈值、估值价格、汇率和分类 snapshot 都是检查输入，不能默认当前值。
- ETF sleeve 检查产品/跟踪资产集中与流动性；个股 sleeve 检查单股、行业、板块、ST/退市与持仓数；合并层再次检查总现金、市场和账户集中度。任一 required scope block 均阻断整体发布。

## 失败、幂等与并发

规则执行异常返回 `RISK_ENGINE_ERROR` 并按 hard block 处理，禁止 fail-open。相同输入与 policy 重跑复用结果；例外审批使用乐观锁，过期自动失效但不删除记录。

## 可观测与安全

监控检查耗时、规则错误、block/warning 分布、告警未确认时长、例外数量和即将到期项。风险阈值修改与例外审批需要完整审计，敏感账户值按权限展示。

## 测试与验收

- 人为制造负现金、超集中、过期信号和未对账，均产生 block 且发布失败。
- 故意让规则抛异常，整体不得 PASS，并产生引擎告警。
- 阈值边界、币种换算、行业分类和 stale snapshot 有黄金案例。
- 相同 breach 不产生告警风暴；解决后新检查为 PASS，旧 breach 仍可查询。
- 单独构造 ETF sleeve PASS、个股 sleeve BLOCK 的案例，合并结果必须 BLOCK；反向案例同样成立且报告具体 scope。

## 不做事项

不做自动平仓，不静默改变策略权重，不允许无期限例外，不把回测风险结果当实际账户风险。
