你是执行者，本文是 risk 模块唯一任务来源；换会话先读 `development/11-risk/PROGRESS.md`。目标是以版本化规则对数据、双策略 sleeve、合并目标/信号、真实执行账户和平台健康做 fail-closed 检查，输出不可变逐规则结果、总体决策、例外与去重告警；绝不修改策略分数、目标权重、建议或成交事实。冲突按“真实账户/对账 > hard block > 时点输入 > 分 scope 证据 > 例外 > warning > 便利”处理。

## 冻结口径

- RuleDefinition 身份不变；RuleVersion 冻结对象阶段(PRE_TRADE/IN_FLIGHT/POST_TRADE)、scope(ETF_TIMING/EQUITY_DAILY_SELECTION/COMBINED_ACCOUNT)、指标、比较符、阈值、严重级别(HARD_BLOCK/APPROVAL_REQUIRED/WARNING)、生效区间、owner、exception_allowed。修改只新增版本。
- PolicyVersion 显式绑定账户/策略/市场与规则版本；required scopes 必须同时含 ETF、个股、合并。有效版本按 `decision_at` 选择，不能默认最新。
- RiskInput 冻结 target/signal/account/market/data/task snapshot IDs、各自 as_of/available_at、价格/汇率/分类版本和 content hash；证券仅 canonical instrument_id。PRE 用目标/建议，POST 只能用 source=`execution_ledger` 的实际账户。
- RuleResult 不可变，保留 observed/threshold/operator/outcome/explanation/scope。总体按 `BLOCK > APPROVAL_REQUIRED > WARNING > PASS`；任一 required scope BLOCK 即整体 BLOCK，聚合不得覆盖分项。
- 规则异常、缺事实、负现金/负持仓、未对账、陈旧输入、过期信号均 fail-closed 为 `RISK_ENGINE_ERROR` 或具体 HARD BLOCK；BLOCK 映射 signals `HARD_FAIL`，仅总体 PASS 映射 `PASS`。
- 事前内置事实覆盖现金、单标的/行业/市场、持仓数、流动性、资格、交易状态、lot、陈旧；事中覆盖过期/价格偏离/部分成交/未执行/超量；事后覆盖实际暴露、现金、回撤、换手、成本、币种、对账、数据/任务健康。
- Exception 单独追加，必须申请人/批准人/理由/scope/expires_at/规则许可和乐观版本；默认 HARD_BLOCK 不可豁免，无无限期；过期自动失效但不删除原结果。豁免只改变 effective decision，不改原 outcome。
- Alert dedupe key=`rule_version+object+scope+observation_window`；重复 breach 不建告警风暴。ACK/ESCALATE/RESOLVE 有版本与证据；只有新检查 PASS 才可解决，旧 breach 仍可查。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/risk/**`、`migrations/011_risk.sql`、`tests/risk/**`、本文、`development/11-risk/**`。
- 01–10、MvpSelect、模块规格、pyproject 只读；禁止联网、装依赖、自动平仓/调权/下单。
- 开工：上游 `939 passed`、88 源码文件；11 规范 SHA256 `69B7E2B1A5F74A55F08380EE1E8C8D9ECFD55ABAA63D4ACDF6E1260D721ACF20`，完成复核。
- MvpSelect 无独立风险引擎且权重裁剪曾有“再归一化突破限制”缺陷；禁止迁移，只可参考指标名称。

## 任务 1：规则与三层检查

- 实现 rule/version/policy/input/run/result/exception/alert/state/event；比较器支持 LT/LE/GT/GE/EQ/IN/TRUE/FALSE，并允许受控 evaluator 注册。
- RunPreTradeChecks/RunInFlightChecks/RunPostTradeChecks：冻结输入哈希幂等；先 ETF、再个股、再合并；逐 scope 留结果与贡献，总体聚合。实现阈值边界、原币+显式 FX、分类快照、stale age、对账和来源校验。
- ETF PASS+个股 BLOCK、反向案例均整体 BLOCK 且指出 scope；规则 evaluator 抛错必须产生 engine-error BLOCK/alert，不得跳过。

## 任务 2：例外、告警与查询

- ApproveException 使用 expected_version；检查 rule 许可、scope 不扩张、明确到期、理由/双人身份；过期/撤销保留记录。effective decision 重算但原 result 不变。
- breach 自动 upsert 告警；实现 acknowledge/escalate/resolve。GetRiskState(account_id,as_of) 返回 active breach、陈旧检查、阻断原因；GetSleeveRisk(target_id) 返回三层结果。
- 新 snapshot 重检 PASS 后显式 resolve；相同输入/policy 复用 run，不重复 alert/event。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `011_risk.sql` 覆盖 rule/version/policy binding/check run/result/exception/alert/event，含版本、唯一键、外键、有效期和事务约束。
- `tests/risk` ≥120 passed、0 skipped；上游 939 仍绿；compileall、mypy 十一模块、文档校验均 0。
- 正向覆盖负现金/负持仓、集中度/行业/市场/持仓数/流动性/资格/停牌/lot/stale、过期/偏离/部分/未执行/超量、回撤/换手/成本/币种/对账/任务健康、三 scope、FX、阈值边界、幂等、告警生命周期、例外并发与 SQLite。
- 反向验证临时把 evaluator 异常改为 PASS 或忽略 required scope，既有测试必须非 0；恢复后全绿。

## 纪律与完成条件

- 禁止 fail-open、默认当前价格/汇率/分类、用回测结果替代真实账户风险、修改上游事实、无限期/越权例外、重复告警、删改/skip/todo 测试、白名单外修改或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实写 BLOCKED；每任务更新 PROGRESS。全量验收最多 3 轮，首轮全绿即停并贴证据。
