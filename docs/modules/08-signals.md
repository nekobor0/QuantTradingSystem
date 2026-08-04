# 08 信号与建议模块

## 目标与边界

把已通过组合构建和事前风控的目标组合冻结成有有效期、可审批、可解释的信号与人工订单建议，连接系统决策和人工执行。

本模块不把建议当成交，不直接连接券商，不从建议推导实际持仓。

## 所有数据

- `signal`：策略/组合版本、生成时点、适用交易日、有效期、发布状态和内容哈希。
- `signal_component`：来源 `strategy_kind`/run、sleeve、`SELECT/KEEP/EXIT` 或 ETF 门控状态及对最终净差额的贡献。
- `recommendation`：`instrument_id`、方向、目标/当前差异、建议数量/限价、估计费用和原因码；证券代码只作带日期解析后的展示字段。
- `recommendation_risk_ref`：事前风控结果引用。
- `approval_decision`：接受、部分接受、拒绝、数量修改、理由、操作者和时间。
- `signal_supersession`：替代关系及旧信号失效原因。

信号不可变；审批是追加事件。建议数量可因审批改变，但原建议保留。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `CreateSignal(target_portfolio_id, account_snapshot_id, pricing_snapshot_id)` | 幂等键为输入哈希；按整手/现金生成建议 |
| Command | `PublishSignal(signal_id)` | 仅 risk=PASS、数据新鲜且账户已对账 |
| Command | `ApproveRecommendation(id, decision, quantity, reason, expected_version)` | 乐观锁；禁止超过建议方向边界 |
| Query | `GetActionableRecommendations(as_of)` | 仅 published、未过期、未替代且剩余数量大于 0 |
| Query | `GetDailyDecisionBoard(as_of)` | 同屏返回 ETF 门控/调仓状态、个股 SELECT/KEEP/EXIT 与合并后的净建议 |
| Event | `SignalPublished` / `RecommendationApproved` / `SignalExpired` | 下游按 event_id 幂等消费 |

## 主流程与状态

信号：`DRAFT → RISK_CHECKED → PUBLISHED → EXPIRED | SUPERSEDED | CLOSED`。建议：`PENDING → APPROVED | PARTIALLY_APPROVED | REJECTED → HANDED_OFF`。

冻结 ETF/个股 `signal_component` 和合并目标 → 以合并目标减实际账户得到唯一净差额 → 用参考价格估算整数股和费用 → 卖出优先释放现金 → 事前风控 → 人工审批 → execution_ledger 建立订单关联。价格变化超过阈值时建议失效并要求重算。

## 业务规则

- 默认 T 收盘后生成、T+1 执行；信号包含 `decision_at`, `valid_for_date`, `expires_at`。
- 纯多头下 SELL 数量不超过已结算可卖持仓；BUY 不得使预计现金为负。
- A 股/ETF/北交所/港股整手、价格步长和费用按 instruments 交易规格及市场 policy 计算。
- 部分接受必须填写数量与原因；用户不能把 BUY 改为 SELL，反向意图须新建人工订单并明确非策略来源。
- 数据门禁失败、账户未对账或 hard risk 均禁止发布。
- 个股 `SELECT/KEEP/EXIT` 是解释信号，不等于三类订单；只有合并目标的净差额产生 BUY/SELL。ETF 非调仓日仍显示日频门控状态，但目标未变时不生成零意义订单。
- 同一 `instrument_id` 每个 signal 最多一条净 recommendation；来源组件可以多条但其贡献之和必须可对账到净差额。

## 失败、幂等与并发

快照陈旧为 `STALE_INPUT`，价格偏离为 `REPRICE_REQUIRED`，审批版本冲突为 `APPROVAL_CONFLICT`。重复发布/审批返回既有结果；成交回填与重新审批并发时以剩余可执行数量校验。

## 可观测与安全

监控待审批、过期、被拒、价格偏离、未执行、部分执行和信号到成交延迟；审批记录属于敏感操作，要求身份、时间和不可变审计。

## 测试与验收

- 给定目标、账户、价格和费用，建议股数/现金余量与手算一致。
- 未对账、hard risk、过期和 stale price 均无法发布或执行。
- 重复点击审批不重复创建订单；并发审批只有一个版本成功。
- 建议与实际成交差异完整保留，成交不会反写原信号。
- 双策略黄金案例同时展示 ETF 状态和个股日频变化；冲突贡献净额后只生成一条建议，且能下钻回两个 strategy run。

## 不做事项

不自动下单，不承诺建议价格成交，不允许编辑已发布信号内容，不把未执行建议计入绩效。
