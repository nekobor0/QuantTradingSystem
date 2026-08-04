# 09 执行台账模块

## 目标与边界

记录人工券商执行的订单、部分成交、多次成交、费用、资金事件和对账，派生唯一可信的实际现金、持仓、可卖数量与成本。

本模块不自动向券商发送订单，不把策略建议视作订单或成交，不允许直接编辑派生持仓余额。

## 所有数据

- `account`：单账户、券商、基准币种、市场权限和启用状态。
- `order`：建议关联或 `MANUAL` 来源、`instrument_id`、券商订单号、方向、数量、限价、状态和提交时间。
- `fill`：订单、`instrument_id`、成交时间、数量、价格、佣金、税、其他费和币种；券商代码按成交时点解析后留作原始字段。
- `cash_event`：入金、出金、换汇、分红、税费及外部引用。
- `ledger_entry`：由 fill/cash event 生成的不可变资金与证券流水。
- `account_snapshot`：按指定时点从台账派生的现金、持仓、可卖数量和哈希。
- `reconciliation` / `reconciliation_item`：系统值、券商值、差异、状态和解决记录。

`fill` 以 `(broker, account_id, broker_fill_id)` 唯一；没有外部 ID 时使用稳定导入行哈希并要求人工确认。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `RecordOrder(order_input, source, idempotency_key)` | 建议来源校验剩余批准数量；人工来源必须有理由 |
| Command | `RecordFill(order_id, fill_input, idempotency_key)` | 原子写 fill 与 ledger entries；数量不得超过订单可成交量 |
| Command | `ImportBrokerStatement(file_hash, format_version)` | 先预览差异，确认后提交；相同哈希只导入一次 |
| Query | `GetAccountSnapshot(account_id, as_of)` | 仅由已生效 ledger 派生，返回 snapshot_id |
| Command | `Reconcile(account_id, broker_snapshot, as_of)` | 生成差异，不自动篡改余额 |
| Event | `OrderRecorded` / `FillRecorded` / `AccountReconciled` | 事件发生时间与录入时间分列 |

## 主流程与状态

订单：`DRAFT → SUBMITTED → PARTIALLY_FILLED → FILLED | CANCELLED | REJECTED`。状态只能由订单/成交事件推进，不可任意回退。

人工提交订单 → 录入或导入券商回报 → 校验证券、方向、累计数量和费用 → 原子追加成交及台账分录 → 刷新账户 snapshot → 收盘导入券商日结 → 对账差异 → 人工解决并保留调整事件。

## 业务规则

- A 股买入形成的证券按市场结算规则更新可卖数量；持仓总量与可卖量分开。
- 港币资产、费用与换汇保留原币；报告按有来源的汇率折算，不能修改原币账。
- 更正错误成交使用 reversal + replacement，不删除或覆盖原记录。
- 部分成交累计不得超过订单数量；取消后不能新增成交，除非记录券商迟到回报并进入异常流程。
- 未对账或有未解释 material 差异时，账户状态为 `BLOCKED_FOR_SIGNAL`。

## 失败、幂等与并发

重复成交返回既有 fill；超量为 `OVERFILL`，币种不符为 `CURRENCY_MISMATCH`，已取消订单迟到成交为 `LATE_FILL_REVIEW`。写入按订单版本加锁；同一导入文件失败须整体回滚。

## 可观测与安全

监控未完成订单、迟到成交、对账差异、负现金/负持仓、费用异常和导入失败。账户号显示需脱敏；导入文件权限受限并记录操作者。

## 测试与验收

- 一单两次部分成交后持仓、现金、费用和订单状态与手算一致。
- 重复导入相同成交/日结文件不改变余额；超量成交被拒绝。
- reversal 后旧记录仍可见，净余额与替代成交一致。
- 对账制造 1 股或 1 元差异会阻断信号，解决后恢复并保留证据。

## 不做事项

不接券商交易 API，不直接修改 position/cash 快照，不用建议单估算值替代真实费用。
