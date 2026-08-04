# V7 续跑上下文

更新时间：2026-08-03 17:08（Asia/Shanghai）

## 新会话唯一入口

依次读取：

1. `GOAL_V7.md`；
2. 本文件；
3. `PROGRESS_V7.md`；
4. `BLOCKED_V7.md`；
5. 当前任务对应的 `V7_*_LEADER_BRIEF.md`。

不要重新阅读顶层旧 checkpoint。V2–V6 的记录、任务书和报告已归档到 `archive/pre_v7/`，摘要见 `archive/pre_v7/SHA256SUMS.md`。需要核查某项历史事实时按文件名进入归档，不要恢复到顶层。

## 顶层保留例外

`GOAL_V6.md`、`PORTFOLIO_EVALUATOR_V5_SPEC.md`、`EVALUATOR_V3_SPEC.md`、`EVALUATOR_V4_SPEC.md` 是现有脚本/测试的路径依赖，仅为复算兼容，不是活动目标。2026-08-03归档后 `python -m pytest tests/research/v6 -q` 仍为77 passed。

## V6不可回溯的死亡边界

- A：固定60月先验收缩ICIR；B：当前Downside Beta；C：30股QAV；D：连续跌停打开×PIT存续；E：50股12-1行业残差动量；F：11月前5行业轮动；G：缺角色时强行计算。
- V6累计68项试验；A–F为 `REJECTED`，G为 `DATA_BLOCKED` 且 `portfolio_computed=false`。
- 新研究必须使用新research_id并标记 `post_v6_hypothesis=true`。2018-07至2026-06只可作开发/诊断，不得称为新独立验证。

## V7任务顺序

1. 公共协议：角色分级、Stage S/P门禁、V7登记与账本校验（不占正式预算）。
2. 首批严格顺序：`C7_CAPACITY_AWARE_QAV` → `B7_LIQUIDITY_FRAGILITY` → `F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION`。
3. 第二批：`E7_FUNDAMENTAL_CONFIRMED_RESIDUAL_MOMENTUM` → `J7_EARNINGS_REVISION_UNDERREACTION`。
4. 条件任务：B与独立Alpha获得资格后运行G固定60/20/20；F、C、E、B满足各自门禁后才能运行跨Lane组合。
5. 后续研究：H指数调样、I供给冲击、K公告文本数据；A不确定性感知stacking只在第二阶段后；D无新强制卖出机制时保持死亡。

每个任务先生成独立leader任务书，任务索引见 `V7_TASK_INDEX.md`。

## 当前机器状态

- 公共治理、C7、B7代码和测试已存在；C7为`SIGNAL_VALID`后Stage P `REJECTED`，B7在Stage S `REJECTED`，均不得进入正式组合。
- 当前任务F7，先读`V7_F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION_LEADER_BRIEF.md`和`artifacts/registrations/f7_industry_earnings_diffusion.md`。
- `fina_indicator`逐股补数已完成2,700/2,700、194,590行、hash/重复键全通过。仍需F7按月`report_rc`：2018-04—2026-07共100项。账户实测1次/分钟、10次/小时、10次/天；程序已改为三层限流和跨日退避，预计约20个自然日。2015-10/11完整旧分片及2015-12单页半成品保留但不验收；项目内没有第二份可验证复用的`report_rc`缓存。用`python -m scripts.v7.backfill_f7_financials --dataset status`查进度，错误看`logs/*.stderr.log`；中断后原命令可安全续跑。
- 2026-08-03 15:46状态仍为report_rc 0/100、pages=0、rows=0；PID 18668存活并因当日10次配额耗尽睡眠至次日本地日。owner文件和上述status命令为权威，文档中的PID只用于当次交叉核验。
- 当前任务另有每6小时heartbeat automation `v7-f7-tushare`（失败才通知），负责进程停止后的断点续跑和数据齐全后的F7 runner；不要重复创建自动化。当前report_rc owner以文件为准；2026-08-03 15:34启动的是PID 18668、nonce `c8ed323b1034451a920b4fb5341a9eca`。
- `backfill_f7_financials`现使用`locks/{dataset}.lock`原子跨进程互斥；status同时报告lock PID/nonce/alive。PID 18668由旧代码启动，已人工补种同PID/nonce的`report_rc.lock`；它退出后新代码会识别死PID、原子接管并在正常退出时清锁。存在活锁时严禁另起worker或删除锁。
- 2026-08-03 17:08：官方`report_rc`文档称单次上限3,000行，但真实旧探针曾返回5,000行；新代码已按首个满页动态学习3,000/5,000有效页上限，并以实际返回行数推进offset。官方请求参数没有目标季度过滤，不能合法减少月度调用数。
- 新代码复用任何分片前校验sidecar SHA256/行数；复用月完成标记前逐页校验hash、行数、offset连续性并重放分页终止状态。单个3,000行歧义满页不能被判完成；完整F7 runner的`require_complete_backfill`也调用同一验收器，不能仅凭100个marker绕过。V7+V6回归146 passed。
- 当前PID 18668仍是加载旧代码的三层限流worker，owner/lock nonce仍为`c8ed323b1034451a920b4fb5341a9eca`。本会话普通权限无法停止（Access denied），提权请求因周额度系统拒绝；因此没有另起worker或删除活锁。安全续跑顺序：先查owner/lock/status；若PID已死，直接用新命令启动并由死锁接管；若仍活且需更换，必须先由有权限的会话停止PID，确认死亡后再启动。任何旧进程产出的marker都必须经过新验收器，不能仅按文件存在认定完成。
- F7主代码为`src/quant_trading_system/research/v7/industry_earnings_diffusion.py`；到数前审计已补齐winsorize、Stage S年度/组件/行业诊断、完整数据manifest/原始质量统计，以及与Lane A一致的ST/退市/ADV/缺失收益执行语义和逐股精确行业贡献。F7专属30项、V7+V6共142项全绿；F7最终报告模板已锁定GOAL规定的15节。尚未生成正式manifest、历史Stage S/P结果或trial 71账本行；这些只能在report_rc 100/100后由完整runner生成。
- 已完成的C7/B7报告已规范为GOAL_V7第13节的1—15节格式；数值、decision、registration/config hash和trial_id均直接继承原evaluation JSON，结论未改变。
- V7正式晋级最终依赖2026-07以后不可覆盖实时影子：月频至少12个月，慢变量至少8次调仓或18个月，事件至少100个可交易事件或预登记功效要求。

## 网络波动续跑规则

任何联网或长计算均写checkpoint、owner PID/nonce、配置hash和输入manifest；网络中断只从已验证checkpoint续跑，不覆盖成功分片。连续两次同一数据缺口稳定复现则记 `DATA_BLOCKED` 并转做不受影响任务。实时影子只追加，不回填改写。
