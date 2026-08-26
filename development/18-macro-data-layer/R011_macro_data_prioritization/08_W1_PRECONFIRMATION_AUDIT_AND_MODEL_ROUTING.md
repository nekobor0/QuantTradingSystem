# R011 W1 预确认审计与 Sol/Luna 执行分工

状态：`READY_FOR_HUMAN_DECISIONS`

## 技术摘要

W1 34 条注册表已通过 9 项结构检查，五包计数为 11/8/5/7/3；现有数据可为 17 条提供独立字段对照，但除 Shibor/PMI 已实施部分外，不具备统一 PIT。官方入口均能形成可执行路径：国家统计局发布页提供计划和实际页面时点，国家数据负责历史数值；人行采用公告页与附件配对；ChinaMoney/CFETS、PBOC Policy 和 ChinaBond 分别承载市场利率、政策事件和收益率曲线。

“5.6 Sol 设计，5.6 Luna 执行获取和初审”**可行，且适合本项目，但只能采用编译器式门禁，不适合完全自治放行**。OpenAI 官方把 GPT-5.6 Sol 定位为复杂推理与编码的旗舰模型，把 GPT-5.6 Luna 定位为成本敏感、高吞吐工作负载；两者都支持工具调用和结构化输出。这与“Sol 冻结契约、Luna 批量执行”的工作形态匹配。[OpenAI 模型选择](https://developers.openai.com/api/docs/models) [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## 1. 数据质量结论

| 检查 | 结果 |
|---|---|
| W1 序列数 | 34/34 |
| ID / canonical ID 唯一 | 通过 |
| 全部存在于 Constitution backlog | 通过 |
| 包计数 | 11 / 8 / 5 / 7 / 3，准确 |
| 来源引用 | 全部注册 |
| 全量回填门禁 | 关闭，等待 W1_D1—D9 |
| 现有对照资产 | 8 个宏观 Bronze 文件；17 条可直接字段对照 |
| PIT 现状 | Shibor/PMI 部分已实现；其他现有 Bronze 不足以证明 PIT |

没有使用图表：这里的核心证据是精确集合、字段映射和布尔门禁，表格比趋势图更适合审计。

## 2. 官方来源与局限

- 国家统计局 2026 发布日程给出 GDP/工业、PMI、CPI/PPI 的具体日期和时间，并说明国家数据通常在正式发布约 3 个工作日后更新。因此发布页和数据库必须配对，不能拿数据库更新时间替代经济发布时间。[国家统计局 2026 发布日程](https://www.stats.gov.cn/xw/tjxw/tzgg/202512/t20251224_1962137.html)
- 2026-07 PMI 官方页同时给出 09:30 页面时间和本项目 8 个 PMI 字段的可核验样例；这验证了扩展现有发布页 parser 的可行性。[国家统计局 2026-07 PMI](https://www.stats.gov.cn/zwfwck/sjfb/202607/t20260731_1964253.html)
- CPI/PPI 官方发布/解读页能提供总体、核心 CPI、PPI 和 PPIRM；2026 年 PPI 基期轮换是必须记录的 methodology version，不能当作无断点长序列。[国家统计局 2026-07 CPI](https://www.stats.gov.cn/sj/zxfbhjd/202608/t20260809_1965008.html) [CPI/PPI 官方解读](https://www.stats.gov.cn/sj/zxfbhjd/202608/t20260809_1965009.html)
- 人行社融公告包含正式页面时间、统计定义与口径调整说明；例如政府债券纳入和金融统计范围调整必须进入 methodology version。[人行社融样例](https://www.pbc.gov.cn/diaochatongjisi/116219/116225/523c260b344c4f1390664430295064a9/index.html)
- 中债历史查询可按期限获取日频曲线，官方说明历史可追溯至 2006-03-01 且单次历史窗口最多一年；这决定了分片和断点恢复设计。[中债历史查询](https://yield.chinabond.com.cn/cbweb-mn/pgxh/showHistory) [中债曲线说明](https://indices.chinabond.com.cn/cbweb-czb-web/czb/bzcxsmDown?locale=)

## 3. 推荐的 Sol/Luna 责任边界

| 工作 | 模型 | 原因 | 强制输出 |
|---|---|---|---|
| 指标定义、单位、累计/单月、制度断点 | Sol | 语义错误会系统性污染全历史 | 冻结 registry + 决策记录 |
| 来源路径、adapter、parser、测试、审计阈值 | Sol | 需要跨网页结构和 PIT 推理 | 可重放脚本 + fixture + tests |
| 按 manifest 执行分页/分年下载 | Luna | 高重复、可恢复、可机器验收 | shard manifest + hash + state |
| 运行 parser 和基础 schema 校验 | Luna | 确定性规则，适合批量 | validation JSON |
| 行数、重复、缺期、值域、哈希初审 | Luna | 可用断言完全约束 | pass/fail + quarantine |
| 解析器失配后的首次分类 | Luna | 可按错误码归类，但不自行修口径 | failure taxonomy |
| 发布时点缺失、口径变化、异常值归因 | Sol | 需要证据权衡，不能机械修补 | adjudication record |
| Bronze 冲突、跨列互换、修订判断 | Sol 复核 | 可能改变历史研究结果 | 双源对账与修复许可 |
| Research Ready 提升 | Sol + 人工确认 | 属于研究治理决策 | signed gate |

## 4. Luna 可执行任务必须满足的“编译器契约”

每个 Luna 工作单必须固定：

1. 允许访问的 source ID、URL 前缀、HTTP 方法、频率和请求间隔；
2. 精确输出目录、分片键、主键、schema、单位和值域；
3. 预期覆盖范围和允许缺口日历；
4. 成功退出码与 JSON schema，不允许以自然语言“看起来正常”放行；
5. 断点状态和幂等规则，相同 payload 必须得到相同哈希/规范化结果；
6. quarantine 条件：HTML 结构漂移、字段缺失、单位变化、发布时间缺失、历史修订、双源差异；
7. 禁止行为：猜字段、插值、静默前填、改 parser、扩大 URL 白名单、覆盖既有 Bronze、提升 readiness；
8. 每包抽样：首片、末片、随机片和所有失败片交给 Sol 复核。

## 5. 建议比例与升级规则

在契约完成后，预计 W1 的请求执行、分片落盘和基础审计约 **60%—75% 的 Agent 工时可交给 Luna**；剩余 25%—40% 包括首次 parser、来源变化、口径判断、PIT 裁决和最终报告，由 Sol 承担。这个比例是工程估算，不是官方模型基准。

Luna 连续两次在同一 shard 失败时停止重试；任何 schema 漂移、单位/频率变化、发布日期缺失、对账差异超过冻结阈值，立即升级 Sol。禁止 Luna 在失败后修改验收标准来让任务通过。

## 6. 风险与稳健性检查

- 风险不在“能否下载”，而在错误数据也可能漂亮地通过行数检查；所以语义和 PIT 必须由 Sol 冻结。
- HTML/PDF 混合附件、中文表头变化、累计口径和历史制度断点是 Luna 最容易做出局部合理但全局错误判断的区域。
- 对一个数据包先做两期 shadow run：Sol 与 Luna 独立执行，逐单元格、manifest 和 audit JSON 完全一致后，才扩大到全历史。
- 每次 adapter 版本变化重新做 shadow run；不能把一次通过永久视作能力证明。

## 7. 下一步

用户确认 W1_D1—D9 后，先用“DR007/R007 + OMO/MLF”作为第一轮 Sol→Luna handoff：Sol 写契约和两期 gold fixture，Luna 回填一个月并运行审计，Sol 只复核异常和四类抽样。通过后再复制到 PMI 扩展、价格、信用和增长包。

