# V7执行进度

更新时间：2026-08-03 17:08（Asia/Shanghai）

## 开工回执

- 目标：按角色分级和Stage S/P分离完成V7研究，最短路径取得defensive与independent_alpha资格并解锁Lane G。
- 顺序：文档归档 → 公共协议 → C7 → B7 → F7 → 第二批与条件组合。
- 最大风险：把已看过的2018-07至2026-06历史结果误称新确认；或为了G纳入已拒候选。
- 基线：V6测试77 passed；V7实现/测试/登记均为0。
- 归档：48份pre-V7历史Markdown已移入 `archive/pre_v7/`，没有删除；顶层保留5份活动/兼容文档，随后新增V7 context文件。

## 当前任务

- 正在执行：`F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION` 不可变数据补取与PIT信号实现。
- 下一正式research_id：`F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION`。
- 后台任务：`report_rc`正式验收范围2018-04—2026-07共100个月（覆盖2018-07首信号的90日共识）。账户实测三层限频1次/分钟、10次/小时、10次/天；按每月约2页估计约20个自然日。2015-10/11完整旧分片及2015-12单页半成品保留但不参与F7，status按目标月份排除。状态命令：`python -m scripts.v7.backfill_f7_financials --dataset status`；日志位于`artifacts/data_backfill_v7/f7_financials/logs/`。
- 财务首进程若留瞬时错误，`financial_auto_resume`隐藏守护会在其自然结束后自动运行同一断点命令；成功分片只读校验，不覆盖。
- 卖方预测另有`report_rc_auto_resume`隐藏守护；当前进程异常结束后最多续跑3次，连续三次仍失败才停止并按协议记阻塞。
- Codex heartbeat automation id=`v7-f7-tushare`已按真实日配额调整为每6小时，附着当前任务、仅失败通知；负责核验owner/log、断点续跑，100个月齐全后自动继续F7 runner与后续leader任务。
- 当前三层限流进程PID=`18668`、nonce=`c8ed323b1034451a920b4fb5341a9eca`；2026-08-03 15:34实测日配额耗尽后正确计算`30405s`退避至下一本地日，不再分钟级空转。
- `backfill_f7_financials --dataset status`现同时输出完整月份、目标分页数、目标累计行数和未完成月份；可观察半月分页进度，不再只看marker。

## 已完成

- 完整读取 `GOAL_V7.md`（805行，SHA256=`88AABA189FEADEA3CE8AB5CE08F495BFF8420C328BE60885EC75FBEFB164CC4E`）。
- 完成pre-V7文档可恢复归档和SHA256清单。
- 2026-08-03 15:46复核归档清单：48个历史Markdown逐文件SHA256校验，Failures=0；`archive/pre_v7/`另含README和清单本身，共50个文件。
- 实测兼容引用：V6测试和冻结脚本直接读取GOAL_V6及V5评价器规范；保留原路径后V6测试77 passed。
- 提取V7任务依赖和条件门禁到 `V7_TASK_INDEX.md`。
- V7公共协议完成：`governance.py`校验唯一research_id、角色、Stage S/P、历史/实时边界、放宽补偿和组合输入资格。
- 公共协议验收：V7 19 passed；V7+V6合并96 passed。反向探针按预期2 failed，证明历史PROMOTE和REJECTED组合输入会被拦截；删除探针后96 passed。
- C7任务前实测：现有面板554,400行；V6 QAV可用370,142行；冻结1000万元、最大2%权重对应ADV>=1000万元后仍有351,132行、5,023股、95个月，月度最少1,259只。
- C7完成：数据审计PASS；Stage S为SIGNAL_VALID（Partial IC=0.0566、HAC t=3.722、89个月、75.3%正月）；Stage P为REJECTED（年化净超额1.97%、IR0.114、单股贡献41.5%及执行约束失败），不写影子。
- C7账本trial_id=69、FDR q=0.00341；该显著性只属历史开发。相对Lane A的20%事后诊断两基准Delta IR为-0.386/-0.319，明确不能改变拒绝结论。
- C7反向验证3项按预期失败：未来财务修订不可见、缺ADV不能通过容量、REJECTED Stage S不能开启Stage P；删除探针后相关测试111 passed。
- B7完成：数据审计PASS（5,533只TDX+242只退市、组件覆盖97.97%）；Stage S REJECTED（下跌月Partial IC=-0.0138、HAC t=-1.392、正月42.2%），未运行Stage P，不提供defensive角色。
- B7账本trial_id=70、FDR q=0.347；与普通Beta相关绝对中位数0.059通过，但独立方向失败。反向探针3项变红，删除后当前相关测试117 passed。
- F7 leader任务书和事前登记已冻结；最终registration SHA256=`F680898280BC54CA1659B2A8B1E2089C6F872B2B5F0ED88EF6A14B1B088B1198`，trial_id=71尚未写入账本。覆盖门禁已在结果前固定为财务项每行业>=5家公司且>=50%公司覆盖、卖方项>=5家公司且>=20%市值覆盖。
- F7机器配置SHA256=`83cb8b1f1600eaded01486daf80dfb4abd5533be37a20a4a6ea81f6f88a43032`；唯一3月期限、000852.SH、BENCHMARK_SPECIFIC、12月live和跨基准放宽补偿已通过公共governance校验。
- F7本地审计：中证1000权重126月/2,700只历史成分；精简财务表覆盖2,406只/158,500行，但缺扣非增速和单季ROE。Tushare单股探针确认目标字段可用；`fina_indicator_vip`无权限，改用逐股可断点补数。
- F7财务补数已完成：2,700/2,700不可变分片、194,590行、errors=0；2,697缓存命中+3个瞬时失败自动补齐。全量验收sidecar/hash错误0、完整键重复0；`q_sales_yoy/dt_netprofit_yoy/q_roe`非空率92.87%/96.02%/95.42%，报告期2015-03—2026-06。
- F7财务PIT预审通过：95个Lane A月份、94,397个中证1000-月成员、2,285只股票；PIT行业覆盖99.365%、市值覆盖99.719%、重复输出键0。247,133条月度PIT财务信号，未来公告违规0。三项财务组件满足“每行业>=5家公司且>=50%覆盖”的行业比例每月最低均为93.55%，95/95个月均超过80%。申万同股重叠705键均为同一行业的Y/N版本重复，多行业冲突0；代码只允许同行业确定性去重，多行业仍fail-closed。
- 完整runner当前按预期拒绝半截输入：`F7 backfill incomplete: financial 2700/2700, report months 0/100`；未写trial 71或历史决策。
- 严格“盈利上修”不能取财报`update_flag`：127,857个多版本键仅51个有多个公告日。官方`report_rc`卖方预测接口可用，000001.SZ在2025-01—2026-07返回382行；实测账户双限频1次/分钟、10次/小时，首个全市场月2015-10为9,339行且分页成功。
- 新增`backfill_f7_financials.py`、PIT信号模块和完整Stage S/P runner；反向测试覆盖未来公告不改旧信号、未来研报不可见、空首页不误判完成、分钟/小时/日配额、1月目标年切换、PIT行业冲突、3月收益、10%零净overlay、Stage S/P和分片不可覆盖。F7专属20项；V7+V6合并132 passed，GOAL哈希不变。
- 2026-08-03 15:46从实际目录重建并复跑回归命令：`python -m pytest -q tests/research/v7 tests/research/v6`，132 passed in 5.99s；旧的扁平V6测试路径不存在，不作为续跑命令。
- 2026-08-03 15:50复核项目缓存：F7目录外没有可验证复用的`report_rc`历史数据；2015-10—12旧探针共22,245行仅用于真实数据冒烟，`analyst_revision_pit`在2015-11/12得到2,791条、1,593只股票、目标季度固定2016Q4，当前/前期最大研报日均未越过各自as-of日。正式范围与冻结构造不变。
- 2026-08-03 16:05完成F7到数前规格审计并补齐三项缺口：四项公司值显式1%/99% winsorize；Stage S输出年度、四组件及逐行业诊断；完整runner将在到数后生成逐文件行数/SHA256/root hash的数据manifest和原始重复键、日期、字段、机构/股票/目标季度质量统计。未改门槛、登记或配置。
- 真实2,700财务分片manifest预验收：2,700文件/194,590行、root SHA256=`f78170c694f323c3a367fdb9eb60c76c80468a694742214431efe97921fb06be`、信号字段重复行0；发现2行`ann_date`为空（002204.SZ/20260331、600638.SH/20251231），PIT按规则丢弃并保留审计计数，不擅自把远高于覆盖门槛的数据判为DATA_BLOCKED。
- 新增F7规格测试后F7专属30 passed；`python -m pytest -q tests/research/v7 tests/research/v6`为142 passed。完整runner仍按预期fail-closed于`report months 0/100`；GOAL、registration、config SHA256分别保持`88AABA...CC4E`、`F68089...1198`、`83cb8b...3032`。
- 2026-08-03 16:17完成Stage P执行语义复核：F7现从冻结stock_basic/ST/ADV标签机械区分“允许新增”和“允许减仓/退市强制退出”；ST、无ADV、无有效持有期收益不得新增，退市持仓可强制退出；仍无法标价的实际持仓按Lane A冻结规则记-100%而非报错或忽略，并报告单月最大相关权重。端到端测试证明不合格股票不接收正tilt、强退持仓不被静默保留。
- Stage P行业贡献已改为逐股实际主动权重×实际标记收益后汇总，测试要求逐行业贡献之和精确等于overlay收益，避免行业内执行落点变化扭曲30%集中度门禁。Stage S未来3月收益只要求首月可真实入场；持有后遇不可交易月份仍按冻结标签继续标记，不错误删掉整段收益。
- 2026-08-03 16:25后台owner仍为PID 18668/nonce `c8ed...`、进程存活，report_rc仍0/100；这是跨日配额等待，无重复worker。
- 2026-08-03 16:34按GOAL_V7第13节补齐标准研究输出：C7、B7 Markdown均从原8/6个合并章节重排为完整1—15节，逐份机器核对章节序号、decision、registration/config hash和trial_id均与原evaluation JSON一致；未重算、未改ledger或结论。F7 writer也由测试锁定15节模板。
- 2026-08-03 16:48发现原owner文件只记录进程、不能互斥；已新增跨进程原子dataset lock、活PID拒绝、死PID自动接管、不可读锁fail-closed和status可观测性。为旧代码启动的PID 18668补种同nonce锁；反向实测第二个`report-rc` CLI以`active dataset lock`退出且未请求网络。当前status显示lock可读、PID 18668 alive；142项回归全绿。
- 2026-08-03 17:08复核Tushare官方`report_rc`文档：数据起始2010年、文档单次上限3,000行、支持分页，但请求参数没有目标季度过滤；现有真实探针曾按5,000行返回，故补数器已改为从首个满页动态学习实际页上限并按实际返回行数推进offset，兼容3,000/5,000两种服务行为。
- 所有缓存财务/研报分片复用前现强制核对sidecar SHA256与行数；研报月完成标记还会逐页核对offset并重放分页状态机。旧worker若在恰好3,000行的歧义满页后误写完成标记，新代码将以`incomplete pagination`拒绝消费；完整F7 runner的到数门禁也直接调用同一验收器，不存在绕过路径。新增反向测试后`python -m pytest -q tests/research/v7 tests/research/v6`为146 passed。
- PID 18668仍加载旧分页代码并在日配额等待。普通权限停止失败（Access denied），提权停止请求又因本周额度系统拒绝，故未绕过权限、未启动第二worker、未删除活锁；其owner/lock仍匹配且进程存活。待该进程自然退出或获得权限后，再由新代码原子接管；在此之前完成标记必须通过上述新验收器才能进入研究。

## 每次更新必须写

完成项、实际命令与结果、产物路径、配置/registration hash、当前决策、下一步、后台进程和阻塞。
