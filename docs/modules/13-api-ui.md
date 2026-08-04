# 13 API 与前端模块

## 目标与边界

提供单账户半自动操作入口：并列展示 ETF 择时状态和个股日频选股信号，审批合并后的净建议，回填订单成交、导入券商日结、处理对账、查看风险与报告。API 负责认证、输入校验和调用应用服务；前端不复制业务规则。

第一阶段使用 FastAPI + Streamlit。若以后替换 React，公开命令/查询契约保持不变。

## 所有数据

- `user_action_audit`：用户、动作、对象、前后版本、结果、时间、correlation_id。
- `ui_preference`：非业务偏好；不得保存风险阈值或账户事实。
- `import_session`：文件哈希、预览结果、确认状态、过期时间和操作者。
- 展示模型只缓存短期查询结果，源事实仍归各业务模块。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Query | `GET /daily-status?as_of=` | 返回数据、策略、风控、对账状态及陈旧标记 |
| Query | `GET /signals/{id}` | 返回目标/当前差异、建议、解释、风险和版本 |
| Query | `GET /daily-decisions?as_of=` | 返回 ETF 门控/调仓状态、个股 SELECT/KEEP/EXIT、sleeve 贡献和净建议 |
| Command | `POST /recommendations/{id}/approval` | 需 `Idempotency-Key` 与 `expected_version` |
| Command | `POST /orders` / `POST /fills` | 调 execution_ledger，不直接写数据库表 |
| Command | `POST /broker-imports:preview` / `:commit` | 预览与提交分离，提交绑定文件哈希 |
| Query | `GET /risk-state` / `GET /reports/{id}` | 只展示已授权账户范围 |
| Event | `UserActionAudited` / `BrokerImportCommitted` | 只发布已提交业务动作，不发布页面点击 |

统一错误体含 `code`, `message`, `correlation_id`, `field_errors`, `retryable`；不得把堆栈或密钥返回前端。

API 中所有证券对象以 `instrument_id` 提交和返回；交易代码与名称只作带 `as_of` 的展示属性，不能作为命令主键。

## 主流程与页面状态

每日驾驶舱先显示阻断状态 → 分区展示 ETF 日频门控/是否调仓与个股 SELECT/KEEP/EXIT → 下钻两个策略 run 和合并过程 → 用户只对净建议接受/部分接受/拒绝 → 手工券商下单 → 回填订单/成交或导入 CSV → 预览校验 → 确认入账 → 收盘对账 → 查看实际风险和报告。

所有命令按钮遵循 `IDLE → SUBMITTING → SUCCEEDED | FAILED`，提交期间禁重复操作；刷新页面从服务端状态恢复，不能凭本地状态猜成功。

## 业务规则

- 有 hard block 时信号发布/审批入口禁用并显示具体规则，不仅显示“系统错误”。
- 价格、数量、币种、时间和费用由结构化字段提交；CSV 未通过预览不能 commit。
- 用户修改建议数量必须填写原因；反向交易作为 MANUAL order 单独录入。
- 所有时间显示交易所时区并同时保留精确时刻；“今天”由 as_of 和时区决定。
- 页面明确区分实际、论文交易和回测；颜色不能是唯一状态表达。
- 页面不得为 ETF 与个股来源贡献分别提供下单按钮；同一证券只能审批组合层生成的一条净 recommendation。

## 失败、幂等与并发

命令超时后前端用 idempotency key 查询结果，不自动换 key 重发。版本冲突返回 409 并要求刷新；校验错误返回 422；业务阻断返回稳定错误码。API 不捕获异常后返回 200。

## 可观测与安全

记录请求耗时、状态码、correlation_id 和业务动作，不记录 token、完整账户号或原始券商文件。即使单用户也要求登录、会话超时、CSRF 防护（如适用）和敏感下载审计。

## 测试与验收

- 从信号审批到两次部分成交再到对账完成的端到端黄金流程通过。
- 双击审批/提交成交只产生一次业务结果；409 后刷新展示最新状态。
- hard block、过期信号、CSV 错列、超量成交都显示可操作错误且不写部分数据。
- API 契约测试验证错误码、版本、时间格式和敏感字段不泄漏。
- 双策略驾驶舱黄金场景验证 ETF 非调仓日无建议、个股日频变化可见、来源冲突已净额且仍可解释。

## 不做事项

不在 Streamlit 回调中计算策略或持仓，不直接连券商，不做多租户 RBAC、移动端或复杂实时推送。
