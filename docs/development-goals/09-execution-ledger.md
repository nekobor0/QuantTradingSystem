你是执行者，本文件是 execution_ledger 模块唯一任务来源；换会话先读 `development/09-execution-ledger/PROGRESS.md`。目标是记录人工券商订单、真实成交和资金事件，并且只从不可变 ledger entries 派生实际现金/持仓/可卖量/成本；任何建议或订单本身都不能改余额。冲突按“券商成交/资金事实 > 不可变与幂等 > 非负持仓/可卖/现金证据 > 对账状态 > 操作便利”处理。

## 冻结口径

- 单账户但模型保留 account_id；Account 保存 broker/base_currency/permissions/status，不暴露完整账号。初始资金也是 CashEvent，不允许构造时直接写余额。
- Order 来源只取 RECOMMENDATION/MANUAL。建议来源必须带 recommendation_id、approved_remaining_quantity 且订单量不超过；MANUAL 必须有理由。订单不产生 ledger entry。
- Fill 唯一键 `(broker, account_id, broker_fill_id)`；无外部 ID 使用显式 stable_row_hash 且 `manually_confirmed=true`。同键同内容幂等，不同内容冲突。累计成交不得超订单量；取消后迟到回报返回 LATE_FILL_REVIEW，不落账。
- 原子追加 Fill 与三类 entry：POSITION 总量、SETTLEMENT 可卖量、CASH 原币。BUY：position +qty、cash -(gross+全部真实费用)、settlement 在 sellable_on +qty；SELL：position/sellable -qty、cash +(gross-fee)。币种必须等于订单/证券交易币种；任何余额不得负。
- 成本采用移动平均：BUY 成本含费用；SELL 按成交前平均成本减少，已实现盈亏单独 entry。更正只用 reversal 全量镜像旧 entries，再 replacement 新 fill；旧 fill 永不删改。
- CashEvent 覆盖 DEPOSIT/WITHDRAWAL/DIVIDEND/TAX/FEE/FX，每币种独立；FX 必须成对原币 entries 和 source rate，不修改历史币值。
- GetAccountSnapshot(as_of) 只聚合 `effective_at <= as_of` entries；总持仓与 sellable 分开，包含 entry watermark/content hash/source=`execution_ledger`。不得缓存后直接编辑。
- Reconcile 对比券商现金/持仓/可卖；任一 material 差异令 account `BLOCKED_FOR_SIGNAL`。Resolve 追加解决证据/必要时显式 Adjustment CashEvent，不能改旧 entry；全清后恢复 ACTIVE。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/execution_ledger/**`、`migrations/009_execution_ledger.sql`、`tests/execution_ledger/**`、本文件、`development/09-execution-ledger/**`。
- 01–08、MvpSelect、模块规格、pyproject 只读；禁止联网/券商 API/装依赖/容器。
- 开工：上游 `666 passed`、本模块 0；09 文档 SHA256 `D5C3504E2922615FB5A1C43DFBADBF0E58D3500356622CBC98563862B8E1838A`，其余保护指纹复核。
- 旧 MvpSelect backtest portfolio 直接可变 cash/positions 且按模拟 order.fill 更新，不满足实盘不可变台账，禁止迁移。

## 任务 1：订单、成交和账本

- 实现 Account/Order/Fill/CashEvent/LedgerEntry/事件及状态机；RecordOrder/RecordFill 全部幂等、版本校验和事务写。
- 黄金案例：一单两次部分成交后订单 PARTIALLY_FILLED→FILLED，现金、费用、总量、T+1 sellable 和移动平均成本手算一致；重复 fill 不变，overfill/currency mismatch/late fill 均不落账。

## 任务 2：快照、更正与对账

- 覆盖入出金/分红/税费/FX，reversal+replacement，历史 as_of 快照稳定；未来 entry 追加不改变旧 snapshot hash。
- Reconcile 生成逐项差异，不自动调账；1 股或 1 元 material 差异阻断信号，Resolve 后恢复且证据仍在。Broker statement file_hash+format_version 幂等，预览后整批确认，失败全回滚。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `009_execution_ledger.sql` 覆盖 account/order/fill/cash_event/ledger_entry/snapshot/reconciliation/item/import/event 的唯一、外键、状态、版本和事务约束。
- execution_ledger ≥100 passed、0 skipped；上游 666 项仍绿；compileall、mypy 九模块、文档校验均 0。
- 反向验证临时允许 order 直接改变 snapshot 或 overfill，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止自动下单、直接写 position/cash、建议推导持仓、覆盖/删除 fill、自动抹平对账、跨币种静默折算、删/skip/todo 测试、白名单外修改或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实记录。每项完成更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴证据。

