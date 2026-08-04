# V6执行进度

更新时间：2026-08-01 03:16（Asia/Shanghai）

## 开工回执

- 目标：固化V5三基线，完成V6 Phase 1基础设施，再运行首轮Downside Beta防御研究。
- 并行支线：审计当前Tushare数据接口最早可用年份，并在版本化暂存区断点补历史。
- 顺序：基线registry → 风险schema → 增量评价 → 交易净额 → 影子流水线 → Downside Beta。
- 最大风险：无Git；必须用SHA256和新文件名保护V5证据，补历史不得覆盖在读快照。
- 基线：研究测试57 passed/0 skipped，全仓1562 tests collected。
- 数据事实：Python 3.12、tushare已安装、本机配置有token，D盘可用约327GB。
- 并发边界：主线只读`artifacts/alpha_phase1/**`；支线只写`artifacts/data_backfill_v6/**`。
- 任务书：`V6_LEADER_BRIEF.md`，长度2507字符。

## 已完成

- Phase 1 五项基础设施已落地：V5三基线漂移注册表、12项风格风险审计、增量组合评价器、策略级交易净额合并、append-only实时影子流水线。
- V5注册表`artifacts/registrations/v5_baselines_v6.json`可重算固定验证指标并校验输入SHA256。
- 首轮`downside_beta_v6`已在看结果前登记；数据审计PASS（554,400行、5,775只股票、96个月、零重复、零未来函数违规）。
- 复审后已先套信号时点可交易股票池再做截面变换，并固定验证上界、主要回撤阶段、容量/成本/显著性门槛；重算结论为`REJECTED`，不得进入实时影子。
- 失败证据：固定验证期相对基线的Downside Beta上升0.011（沪深300）和0.026（中证1000），主要基准回撤阶段收益分别恶化0.74和2.31个百分点。
- 多重检验账本已追加为第63项；先按月份合并两个相关基准后，下跌月相对基线收益变化均值为-0.142%，HAC t=-5.023，双侧p=0.00000051，区块bootstrap 95%区间[-0.201%,-0.086%]。FDR显著但方向不利，维持拒绝。
- 已补齐GOAL标准输出模板：`artifacts/evaluations/downside_beta_v6_report.md`；容量现同时保存100万/500万/1000万元三档及5% ADV最低容量。冻结配置完整复算后结论仍为`REJECTED`。
- Phase 1验收矩阵：`V6_PHASE1_ACCEPTANCE_2026-08-01.md`；A/B/C分级器已fail-closed落地。加入回填显式SDK超时后，最新V6测试50 passed、全仓1612 passed，M1六项均有直接证据。

## Tushare历史补齐支线

- 只读审计已完成：本地研究资产、生产数据层、接口自然起点、权限、单次限制、主键、异常和预计补量均写入`artifacts/data_audits/tushare_history_v6.{json,md}`。
- 历史起点不统一：A股行情/估值与复权因子可到1990年，沪深300/中证1000指数日线分别到2002/2004年，资金流与融资融券到2010年，ST接口官方仅到2016年；回填必须按接口自然起点，禁止从1990年机械发送空请求。
- 独立抓取器：`scripts/v6/backfill_tushare_v6.py`默认只执行离线dry-run；联网必须显式指定`--execute --phase <name>`，单阶段断点执行，最高60次/分、2 workers。
- 写入边界：仅允许`artifacts/data_backfill_v6/**` immutable shards和独立run manifest；不得写生产库、`artifacts/alpha_phase1/**`、V5聚合文件或V5 manifest。
- 并发结论：V6读取冻结资产时可并行做dry-run或独立staging；未建立共享限流器时不得同时运行其他Tushare抓取任务，聚合与发布必须等待V6计算空窗。
- 发布门禁：ST的18个源空洞日不可填零；申万成员1984日期、股东人数1900/2053日期须隔离；财务必须保留公告日与`update_flag`；质押分片未达到完整manifest前不得发布。
- 执行状态：旧协议分片保留为审计证据；修复后的v2种子3/3和`daily_1990_2004` 1,378/1,378均完成。日线逐片审计PASS，共2,182,795行、1990-12-19—2004-12-31。
- `adj_factor`经历两次可审计网络挂起：首次保留1,704个成功分片，第二次续跑已修复`19930330`空响应；卡死PID及遗留锁均在核验owner后清理，checkpoint未改写。
- 第三次续跑在5,932/8,694处再次网络挂起，另有`20101206`一次`ChunkedEncodingError`；超过5分钟无checkpoint后精确终止PID并核验清理遗留锁，成功缓存和中断证据均保留。
- 第四次续跑03:16为6,238/8,694（71.75%；6,167 cached、71 fetched），已跨旧断点并补齐`20101206`，错误清零；manifest明确记录15秒SDK超时。任何阶段两次仍失败即停、仍不发布。
- 04:07实时检查：`adj_factor` 7,816/8,694（89.90%；6,167 cached、1,649 fetched），PID 27984及全局锁正常，checkpoint连续更新，无empty/error；guardian将于完成后自动审计并串行进入`daily_basic`。
- 第五次长挂：推进至8,442/8,694（97.10%）后超过5分钟无checkpoint更新。已按owner核验流程终止cell 294/PID 27984并只清理遗留锁；2,275个本轮fetched与6,167个cached分片均保留，冷却后从剩余252项续跑。
- 04:56恢复：放弃会受桌面作业生命周期终止的隐藏后台方式，改用1小时shell timeout的可续接cell 392；唯一owner PID 18160。04:58新checkpoint已重扫2,144/8,694，均为cached，目标仍是跨过8,442后只抓剩余252项。
- 05:05修复checkpoint O(n²)写盘：每25项/异常/终态原子落盘，新增测试后backfill 25 passed、V6 50 passed。`adj_factor`随后8,694/8,694完成，审计PASS（18,879,553行，1990-12-19—2026-07-31）。
- `daily_basic`首次在沙箱内因WinError 10013停止（180 error、0 shard）；提权联网重启后05:13为50/6,732 fetched、0 error，当前guardian cell 417继续运行。
- 05:16主动将一小时guardian切换为24小时联网cell 426，避免已知工具超时；05:17为175/6,732（126 cached、49 fetched、0 error），全局锁唯一owner PID 39048。
- 05:33：`daily_basic` 700/6,732（10.40%；126 cached、574 fetched、0 error），最近交易日1993-09-15；24小时guardian稳定。
- 05:54：`daily_basic` 1,400/6,732（20.80%；126 cached、1,274 fetched、0 error），最近交易日1996-07-03。
- 06:16：`daily_basic` 2,100/6,732（31.19%；126 cached、1,974 fetched、0 error），最近交易日1999-05-20。
- 06:38：`daily_basic` 2,800/6,732（41.59%；126 cached、2,674 fetched、0 error），最近交易日2002-04-22。
- 06:57：`daily_basic` 3,400/6,732（50.51%；126 cached、3,274 fetched、0 error），最近交易日2004-10-18。
- 07:18：`daily_basic` 4,050/6,732（60.16%；126 cached、3,924 fetched、0 error），最近交易日2007-06-25。
- 07:40：`daily_basic` 4,725/6,732（70.19%；126 cached、4,599 fetched、0 error），最近交易日2010-03-29。
- 07:52晨间核验：`daily_basic` 5,075/6,732（75.39%；126 cached、4,949 fetched、0 error），最近交易日2011-09-01；D盘剩余303.8GB。
- 08:03：`daily_basic` 5,400/6,732（80.21%；126 cached、5,274 fetched、0 error），最近交易日2013-01-07。
- 08:26：`daily_basic` 6,075/6,732（90.24%；126 cached、5,949 fetched、0 error），最近交易日2015-10-22。
- 08:49：`daily_basic` 6,732/6,732完成，独立审计PASS（8,842,324行，1990-12-19—2018-06-29）。清理一个遗留重复guardian后，唯一原链切换至`moneyflow`；08:54为50/2,020 fetched、0 error。
- 10:06：`moneyflow` 2,020/2,020完成，独立审计PASS（4,841,995行，2010-01-05—2018-04-27）。`margin_detail`于10:08为50/2,006 fetched、0 error。
- 11:12：`margin_detail` 2,006/2,006完成，独立审计PASS（1,214,919行，2010-03-31—2018-06-29）。`stk_limit`于11:13为50/2,795 fetched、0 error。
- 12:45：`stk_limit` 2,795/2,795完成，独立审计PASS（6,484,477行，2007-01-04—2018-06-29，request-set hash=`802e17b3314d0b7578be60a9948fc298b06297735bd833f31d629868b93aaf40`，staging only）。guardian已切换到`stock_st`；该接口的源空响应不落盘、不计完成，并在两轮仍不完整时失败关闭。
- 13:37：`stock_st`两轮复验后保持`DATA_BLOCKED`：607个交易日任务中453 valid、154 missing，32,889行，实际可返回范围2016-08-09—2018-06-29；首轮网络错误已于第二轮补齐，154个源空日期稳定复现并完整写入审计失败清单，未发布生产库。
- 13:40：新增guardian `-StartPhase`断点参数并通过PowerShell语法解析；从`financial`继续独立阶段，checkpoint=`financial_20260801T053832415250Z.json`，43/6,555（42 fetched、1 source_empty），owner PID 38528。
- 14:04：`financial` 675/6,555（10.30%；662 fetched、11 source_empty、2个可重试`ChunkedEncodingError`），checkpoint持续更新；长运行guardian cell 794与owner PID 38528正常。
- 14:28：`financial` 1,325/6,555（20.21%；1,306 fetched、17 source_empty、2个可重试错误），过去650个任务无新增网络错误；同一guardian、锁和checkpoint持续健康。
- 14:51：`financial` 2,000/6,555（30.51%；1,980 fetched、18 source_empty、2个可重试错误）；自20%里程碑以来错误计数未增加，cell 794与checkpoint持续健康。
- 15:13：`financial` 2,625/6,555（40.05%；2,604 fetched、18 source_empty、3个可重试`ChunkedEncodingError`）；无schema/分页错误，cell 794、锁和checkpoint健康。
- 15:38：`financial` 3,300/6,555（50.34%；3,277 fetched、18 source_empty、5个可重试`ChunkedEncodingError`）；错误仍仅为瞬时响应提前结束，无schema/分页异常。
- 16:03：`financial` 3,950/6,555（60.26%；3,924 fetched、21 source_empty、5个可重试错误）；自50%以来无新增错误，沪市分片继续稳定推进。
- 16:18：当前工作树V6测试重跑为51 passed/0 failed；`financial`同期4,325/6,555（65.98%；4,295 fetched、25 source_empty、5 error），唯一owner PID 38528、全局锁和checkpoint持续健康。
- 16:29：`financial` 4,600/6,555（70.18%；4,568 fetched、27 source_empty、5 error、272,733行）；自60%里程碑以来无新增传输错误。当前全仓收集1,613 tests，V6实跑51 passed。
- 16:55：`financial` 5,275/6,555（80.47%；5,237 fetched、32 source_empty、6 error、314,412行）；70%—80%区间只新增1个瞬时传输错误，owner、锁与checkpoint全程稳定。
- 17:03后旧`financial` checkpoint停在5,490/6,555超过5分钟；30秒CPU仅增0.203秒，判定为SDK长挂。已终止旧cell 794及精确owner PID 38528，核验nonce后只清理遗留锁，所有分片和checkpoint保留。
- 17:10从`financial`重启guardian cell 1057，新owner PID 38488、checkpoint=`financial_20260801T091003975946Z.json`；17:11为427/6,555，其中419 cached、2 fetched、6 source_empty、0 error，证明hash校验断点续跑生效。
- 17:25恢复轮已越过旧断点并到5,900/6,555（90.01%；5,625 cached、243 fetched、32 source_empty、0 error、352,106行）；旧轮6个网络错误全部未复现，继续完成尾段。
- 17:48与17:53两轮分别在6,450和4,475项出现`PermissionError [WinError 5]`；定位为Windows监视读取与checkpoint原子replace的瞬时冲突，不是Tushare数据错误。`write_json_atomic`现仅对`PermissionError`做10次×50ms有限重试，新增回归测试，backfill 26 passed。
- 17:56修复后从`financial`再续跑：guardian cell 1092、owner PID 35272、checkpoint=`financial_20260801T095601171935Z.json`；17:57为425/6,555（419 cached、6 source_empty、0 error）。
- 18:07 `financial`两轮复验完成并正式审计为`DATA_BLOCKED`：6,555任务中6,521 valid、34 missing，380,320行、75,971,414字节，request-set hash=`2004f9062c933caca7a970d0b09fe532afd41fa92b2a23c5ef0eef3ce032db73`。最终网络错误0，34项均为稳定源空；审计文件=`artifacts/data_audits/tushare_backfill_financial_v6.json`，未发布生产库。
- 18:20 `index`两轮复验后正式审计为`DATA_BLOCKED`：259任务中256 valid、3 missing，115,738行，2002-01-04—2017-12-29，request-set hash=`a073805b34a3db4f232ed2f879ef9793b5c478f017d9b518b95da3beec5eb00a`。三个缺口均为2016-01月，但分别属于沪深300/中证500/中证1000指数权重；增强审计现保存dataset/API/request hash，避免同名key歧义。
- 18:32最后的`event`阶段85/829（10.25%；21 fetched、64 source_empty、0 error），当前在`repurchase`历史月份；guardian cell 1132、owner PID 41076正常。审计身份/date bounds与Windows checkpoint回归测试合计27 passed。
- 18:37 `event` 175/829（21.11%；93 fetched、82 source_empty、0 error），推进至repurchase 2015-06。新增全阶段fail-closed汇总器`summarize_tushare_backfill_v6.py`及测试，Tushare回填/审计/汇总测试28 passed。
- 18:53 `event` 475/829（57.30%；319 fetched、156 source_empty、0 error），已到stk_holdertrade 2016-06；2006年后有效月份增加，阶段速率恢复。
- 19:33 `event`两轮结束并正式审计为`DATA_BLOCKED`：645/829 valid、184 missing、228,429行，ann_date 1991-12-30—2026-06-11，request-set hash=`f6e64f69ebf894287e2272a5ce35a7847d952d4167a2cf8bbc04607e007b8415`，最终error=0。
- Tushare总体验收=`DATA_BLOCKED_PARTIAL`：11/11阶段审计齐全、invalid/missing audit均0，7 PASS、4 DATA_BLOCKED（stock_st/financial/index/event），合计43,222,321行、1,742,332,805字节，发布门禁保持禁止。失败checkpoint的5个`.tmp`已在无锁/无进程状态下清理，正式checkpoint与分片均保留。
- 最终验证：GOAL_V6 SHA256仍为`4030CA236BDC3931A380D6C8C91577827C9087326C4E666C19AB97136B68F48F`；三基线registry check PASS；V6 54 passed；全仓1616 passed；Downside Beta完整复算数据审计PASS且决策仍为`REJECTED`。
