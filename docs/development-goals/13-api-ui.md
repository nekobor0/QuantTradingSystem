你是执行者，本文是 api_ui 模块唯一任务来源；换会话先读 `development/13-api-ui/PROGRESS.md`。目标是交付单账户半自动 FastAPI + Streamlit 入口：只做认证、校验、应用服务编排、展示和审计，不复制策略/组合/风控/账本规则，不直写上游表。冲突按“认证/授权 > hard block > 幂等/版本 > 上游事实 > 审计 > UI 便利”处理。

## 冻结口径

- 当前环境实测 FastAPI 0.128.0、Pydantic 2.12.5、Streamlit 可导入，但 pyproject 未声明；本模块白名单不改前序冻结 manifest，真实发布依赖补齐记入 BLOCKED 并由 platform_operations 验收。
- API 服务通过 TradingBackend/Application ports 调用 signals、execution_ledger、risk、reporting；禁止直接写其表。所有命令主键只收 UUID instrument_id/object_id，代码/名称仅为带 display_as_of 的显示字段。
- Session 单账户但仍需登录、超时、撤销、account scope；服务端仅存 token/csrf hash，不记录密码/token。所有 state-changing POST 要 session + CSRF + Idempotency-Key + expected_version（新建命令版本按 0）。
- 命令幂等键=`user+action+key`；同键同 payload 返回原结果，不同 payload 409。超时后客户端查原 key，不自动换 key。乐观锁冲突 409/REFRESH_REQUIRED，校验 422，认证 401/403，hard block 409/BUSINESS_BLOCK；异常不得返回 200/堆栈。
- 统一 ErrorBody=`code,message,correlation_id,field_errors,retryable`；correlation_id 每请求贯穿响应/audit。日志/audit 不含 token、密码、完整账号、原始 CSV。
- audit 只记录已提交业务动作的 user/action/object/before_version/after_version/result/time/correlation；页面点击不记事件。UiPreference 只含主题/时区/分页等非业务偏好，禁止阈值/仓位/账户事实。
- Broker import：preview 仅保存 file_hash、schema/version、列校验摘要、操作者和过期；不存原文件。commit 必须绑定同 hash、未过期且 preview PASS，幂等后调用 backend 原子提交。
- 驾驶舱先显示 hard block/对账/陈旧状态；并列展示 ETF daily gate/是否调仓和个股 SELECT/KEEP/EXIT，显示 sleeve 贡献与组合净建议。只能审批组合层单条净 recommendation，禁止 sleeve 下单按钮。
- 页面命令状态 IDLE→SUBMITTING→SUCCEEDED|FAILED；按钮提交时禁用，刷新从服务端恢复。实际/PAPER/BACKTEST 文字标签+颜色双重表达；时间响应同时含 UTC 精确值、交易所时区值与 as_of。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/api_ui/**`、`migrations/013_api_ui.sql`、`tests/api_ui/**`、本文、`development/13-api-ui/**`。
- 01–12、MvpSelect、模块规格、pyproject 只读；禁止联网/装依赖/直连券商/多租户 RBAC。
- 开工：上游 `1197 passed`、104 源码文件；13 规范 SHA256 `29EC627EA8C773670157C0C0F9DDFED928D361D05304A589A2B4EA0B0F5F0E1B`，完成复核。
- MvpSelect API 使用 mock 全局字典，部分校验异常返回 HTTP 200、错误可能回显文本；禁止迁移。

## 任务 1：会话、应用门面与 API

- 实现 AuthSession/UserActionAudit/UiPreference/ImportSession/IdempotentCommand/API event；密码验证器和 backend 为注入端口。
- FastAPI 路由：login/logout、GET daily-status/signals/daily-decisions/risk-state/reports，POST approval/orders/fills/import preview/commit；Pydantic DTO 禁 extra、UUID/Decimal/aware datetime、结构化费用。
- 中间件 correlation、安全响应头、请求耗时；异常稳定映射且脱敏。GET 只读不审计业务事件；POST 成功原子保存幂等结果+audit。

## 任务 2：驾驶舱与黄金闭环

- canonical view models/Streamlit 页面只渲染 backend DTO；hard block 禁用审批并显示规则。双策略解释保留但订单入口仅净建议。
- 端到端：发布信号的净建议→接受/部分接受→手工 order→两次 fill→import preview/commit→reconcile 完成→risk/report 可查；双击只一份结果，版本冲突刷新恢复。
- CSV 错列、超量成交、过期 signal、hard block、跨账户、过期 session/CSRF 均有可操作错误且无部分写。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `013_api_ui.sql` 覆盖 session/audit/preference/import/idempotent command/event，含 hash、TTL、唯一键、版本和事务约束。
- `tests/api_ui` ≥120 passed、0 skipped；FastAPI TestClient 契约/安全/E2E 与 Streamlit view model；上游 1197 仍绿；compileall、mypy 十三模块、文档校验均 0。
- 反向验证临时跳过 CSRF 或允许 hard block 审批，既有测试必须非 0；恢复后全绿。

## 纪律与完成条件

- 禁止 mock 冒充真实闭环、异常返回 200、保存原 CSV/token/密码、前端计算业务规则、symbol 作命令键、sleeve 独立下单、自动换幂等 key、业务偏好入 UI preference、删改/skip/todo 测试、白名单外修改或 `|| true`。
- PostgreSQL live 与发布依赖缺口写 BLOCKED；每任务更新 PROGRESS。全量验收最多 3 轮，首轮全绿即停并贴证据。
