# V6续跑上下文（自动更新）

更新时间：2026-08-01 03:16（Asia/Shanghai）

## 1. 最高目标与索引

- 最高约束：`development/16-alpha-factor-phase1/GOAL_V6.md`
- SHA256：`4030CA236BDC3931A380D6C8C91577827C9087326C4E666C19AB97136B68F48F`
- Leader任务书：`V6_LEADER_BRIEF.md`
- 详细Checkpoint：`CHECKPOINT_V6_2026-07-31.md`
- 实时进度：`PROGRESS_V6.md`
- 当前无Git；V5代码、冻结产物和`artifacts/alpha_phase1/tushare/**`只读。

`GOAL_V6.md`内容索引：

- L28—106：总目标、V5冻结口径、开发/固定验证/影子切分。
- L107—166：共享数据、特征、评价器、策略、组合和artifact架构。
- L169—247：Lane A指数增强与三个冻结基线。
- L248—330：Lane B横截面防御、Downside Beta定义与晋级门槛。
- L331—508：基本面、底部反转、股票动量、行业轮动。
- L509—616：总组合配置器及A/B/C研究分级。
- L617—782：10步自主研究Loop；登记→审计→信号→评价→边际组合→稳健性→成本→FDR→决策。
- L783—867：每轮研究预算、禁止事项、多重检验/模型风险。
- L868—952：实时影子保护和Phase 1—7顺序。
- L953—1022：M1—M5里程碑和V6完成条件。
- L1023—1114：每轮标准输出模板和最高原则。

## 2. 主线已完成

- Phase 1基础设施：V5三基线registry、12项风格风险模型（PIT区分银行/券商/保险）、固定验证增量评价器、策略交易净额、append-only影子框架。
- V5 registry `--check`：PASS，3 baselines。
- 首轮唯一候选`downside_beta_v6`已事前登记、复审修正股票池口径并重算，最终`REJECTED`；不得调窗/调权重或进入影子。
- 固定验证Downside Beta相对基线上升：沪深300 +0.0113，中证1000 +0.0265；主要回撤阶段分别恶化0.74pp/2.31pp。
- 第63项试验：下跌月候选相对基线均值-0.1423%，HAC t=-5.023，p=5.09e-7，bootstrap 95%区间[-0.2014%,-0.0860%]；FDR显著但方向不利。
- 最新验证：V6测试50 passed，全仓1612 passed。Downside Beta已按冻结配置完整复算，结论仍为`REJECTED`；标准十段式报告为`artifacts/evaluations/downside_beta_v6_report.md`，Phase 1逐项验收为`V6_PHASE1_ACCEPTANCE_2026-08-01.md`。

## 3. Tushare支线边界

- 只写`artifacts/data_backfill_v6/v2/**`；旧`artifacts/data_backfill_v6/shards/**`保留审计，不发布。
- 单进程全局锁、60 calls/min、2 workers；token只从本机配置读取，不落日志/manifest。
- 每个非空分片必须有request identity sidecar、内容SHA256、schema、行数、日期边界；空响应不落盘、不算完成，最多重试3次。
- 当前生产普通日线已有TDX 2005—2026，只补真正缺口1990—2004；2005—2017不重复灌入。
- 2018年前研究字段按本地首日减一天截断，禁止重复抓已有快照。

## 4. 当前精确断点

- v2 seed：PASS，3/3，18,882行；审计`artifacts/data_audits/tushare_backfill_seed_v6.json`。
- `daily_1990_2004`：已完成并独立审计PASS，1,378/1,378有效，2,182,795行，范围1990-12-19—2004-12-31，request-set hash `acdcecf3381ac41147509759ca0aae34e691cad4c886b2528d25f7316e58cfc6`。
- 已只读核验：Tushare直接查`T600018.SH`为空；查`600018.SH`在2000-07-19—2004-12-31返回1,065行。代码已登记内部别名`T600018.SH -> 600018.SH`，目标分片仍为`T600018_SH`，sidecar保留`_target_ts_code` lineage。
- 日线审计：`artifacts/data_audits/tushare_backfill_daily_1990_2004_v6.json`；未发布生产库。
- `adj_factor`首次运行在1,705/8,694后因网络/SDK线程超过6分钟无checkpoint而终止；保留1,704个成功分片和1个`source_empty`中断checkpoint。第一次续跑修复了`19930330`空响应，但网络区再次挂起，保留其checkpoint。两个卡死PID和各自确认遗留锁均按owner核验后清理，历史checkpoint未改写。
- 第三次续跑推进到5,932/8,694时累计5,931个有效分片（另有`20101206`一次`ChunkedEncodingError`）后再次网络挂起；超过5分钟无checkpoint后精确终止PID 17404并核验清理遗留锁，所有成功缓存和中断checkpoint保留。
- 第四次续跑于2026-08-01 03:04启动，加载当前代码并在manifest明确记录`request_timeout_seconds=15`；03:16为6,238/8,694（71.75%；6,167 cached、71 fetched），已跨旧断点，`20101206`缺口补齐，错误计数清零。当前PID 27984、全局锁正常。
- 代码新增显式SDK `--request-timeout`并写入checkpoint，守护后续阶段固定15秒；回填测试24 passed。当前已经启动的`adj_factor`进程manifest尚无该字段，表明它加载的是改动前模块；因其已恢复健康，不为元数据补项中断，后续新阶段使用新代码。
- `scripts/v6/run_tushare_backfill_sequence_v6.ps1`继续负责：当前阶段完成后审计，再按本节白名单串行执行余下阶段；任一阶段两次仍不完整或审计失败即停止，不发布生产库。

## 5. 夜间顺序

严格串行（全局锁禁止并行下载）：

1. 完成并审计`daily_1990_2004`（1,378任务）。
2. `adj_factor`全历史（8,694任务；生产层当前为空）。
3. `daily_basic`至2018-07-01（6,732任务）。
4. `moneyflow`至2018-05-01（2,020任务）。
5. `margin_detail`至2018-07-01（2,006任务）。
6. `stk_limit`至2018-07-01（2,795任务）。
7. `stock_st` 2016-01-01—2018-07-01（607任务）。
8. `financial`至2016-03-13（6,555任务，100条分页，保留ann_date/update_flag）。
9. `index`只补本地2018/2016起点前缺口（259任务）。
10. `event`只补本地起点前缺口，质押只补缺失股票（829任务）。

每阶段：execute → 如INCOMPLETE只重试缺口 → `audit_tushare_backfill_phase_v6.py` → 更新本文件、`PROGRESS_V6.md`与Checkpoint。不得聚合或发布生产库。

## 6. 续跑命令模板

```powershell
$env:PYTHONPATH='src'
python -m scripts.v6.backfill_tushare_v6 --status --output-dir artifacts/data_backfill_v6/v2
python -m scripts.v6.backfill_tushare_v6 --execute --phase <phase> --output-dir artifacts/data_backfill_v6/v2 --config D:\Claude_work_Territory\MvpSelect\configs\settings.yaml --workers 2 --calls-per-minute 60
python -m scripts.v6.audit_tushare_backfill_phase_v6 --phase <phase> --output-dir artifacts/data_backfill_v6/v2 --audit-output artifacts/data_audits/tushare_backfill_<phase>_v6.json
# 当前adj_factor结束后的串行守护入口：
powershell -ExecutionPolicy Bypass -File scripts/v6/run_tushare_backfill_sequence_v6.ps1
```

## 7. 额度/中断保护

- 系统未提供账户“周额度剩余百分比”；当前goal工具只返回累计token使用，不返回remaining比例。
- 因此不等待1%才首次落盘：本文件已是可独立续跑的压缩上下文，之后每个阶段完成即更新。
- 若会话突然中断，新会话先读：`GOAL_V6.md` → 本文件 → `CHECKPOINT_V6_2026-07-31.md` → 最新phase checkpoint/status；不要从头抓取。

## 8. 2026-08-01 04:07 实时断点

- 串行 guardian 的执行单元为 cell `294`；`adj_factor` 锁 owner 为 PID `27984`，started_at_utc=`2026-07-31T19:04:28.013367+00:00`。
- 当前 checkpoint：`artifacts/data_backfill_v6/v2/checkpoints/adj_factor_20260731T190428011364Z.json`。
- 最近确认进度：7,816/8,694（89.90%），counts=`cached 6,167 / fetched 1,649`，`request_timeout_seconds=15`，无 empty/error，checkpoint 持续更新。
- 若该 PID 仍存活且 checkpoint 更新，禁止启动第二个抓取器；仅在超过正常重试窗口且连续约5分钟无更新、CPU近乎不变时，才按 owner 核验流程停止精确 PID 并清理唯一遗留锁。
- 当前 goal 仍为 active；V6主线已完成，未完成项仅为Tushare分阶段补齐、逐阶段审计、最终数据验收与GOAL逐条复核。
- 04:27后第五次网络/SDK长挂：checkpoint停在8,442/8,694（97.10%；6,167 cached、2,275 fetched）超过5分钟，CPU仅缓慢漂移。已终止cell 294，核验锁owner/phase/nonce后精确停止PID 27984，再确认进程死亡并只删除该遗留锁；所有shard与checkpoint保留。下一步冷却后重启同一guardian，缓存续跑剩余252项。
- 04:56最终恢复方式：隐藏后台进程会被桌面作业生命周期终止，因此不再使用。当前唯一有效guardian运行在长超时cell `392`，Python owner PID `18160`，checkpoint=`adj_factor_20260731T205643664641Z.json`；04:58为2,144/8,694且全部cached。shell timeout=1小时，cell提前yield不会杀进程；继续用`functions.wait`守护。
- 05:05根因修复：`run_tasks`原先每个结果都重算全量counts并重写增长中的checkpoint JSON，导致续跑O(n²) I/O；现改为结果仍逐项保存在内存，但每25项/异常/最终状态原子落盘。新增批量写测试，backfill 25 passed、V6 50 passed。
- `adj_factor`最终完成并审计PASS：8,694/8,694，18,879,553行，1990-12-19—2026-07-31，request-set hash=`baf233e7a6c3d32bc322500ef60958120af42220b2c5a9c075dcf22cfd8e8480`，明确未发布生产库。
- 当前联网guardian为提权后的cell `417`；`daily_basic` checkpoint=`daily_basic_20260731T211220356402Z.json`，05:13为50/6,732且全部fetched，无error。此前沙箱内180个WinError 10013只存在失败checkpoint，没有落盘空数据。
- 05:16为避免cell 417的一小时shell上限中途终止，已在核验owner后主动断点切换到24小时联网guardian cell `426`。最新checkpoint=`daily_basic_20260731T211607750201Z.json`；05:17为175/6,732（126 cached、49 fetched、0 error），owner PID 39048。
- 05:33里程碑：`daily_basic` 700/6,732（10.40%；126 cached、574 fetched、0 error），最近交易日1993-09-15；cell 426与owner PID 39048持续健康。
- 05:54里程碑：`daily_basic` 1,400/6,732（20.80%；126 cached、1,274 fetched、0 error），最近交易日1996-07-03；同一24小时guardian持续健康。
- 06:16里程碑：`daily_basic` 2,100/6,732（31.19%；126 cached、1,974 fetched、0 error），最近交易日1999-05-20；cell 426持续健康。
- 06:38里程碑：`daily_basic` 2,800/6,732（41.59%；126 cached、2,674 fetched、0 error），最近交易日2002-04-22；cell 426持续健康。
- 06:57里程碑：`daily_basic` 3,400/6,732（50.51%；126 cached、3,274 fetched、0 error），最近交易日2004-10-18；cell 426持续健康。
- 07:18里程碑：`daily_basic` 4,050/6,732（60.16%；126 cached、3,924 fetched、0 error），最近交易日2007-06-25；cell 426持续健康。
- 07:40里程碑：`daily_basic` 4,725/6,732（70.19%；126 cached、4,599 fetched、0 error），最近交易日2010-03-29；cell 426持续健康。
- 07:52晨间核验：`daily_basic` 5,075/6,732（75.39%；126 cached、4,949 fetched、0 error），最近交易日2011-09-01；owner PID 39048、cell 426正常。D盘剩余303.8GB，当前v2 shards约0.6GB，无容量风险。
- 08:03里程碑：`daily_basic` 5,400/6,732（80.21%；126 cached、5,274 fetched、0 error），最近交易日2013-01-07；cell 426持续健康。
- 08:26里程碑：`daily_basic` 6,075/6,732（90.24%；126 cached、5,949 fetched、0 error），最近交易日2015-10-22；cell 426持续健康。
- 08:49 `daily_basic`完成：6,732/6,732（126 cached、6,606 fetched、0 error）；独立审计PASS，8,842,324行，1990-12-19—2018-06-29，未发布生产库。
- 阶段切换时发现早先遗留的重复guardian开始重扫`adj_factor`；已根据父子命令行只停止重复链PID 9452/24024，保留原审计链PID 28696/30808。原guardian现唯一执行`moneyflow`，checkpoint=`moneyflow_20260801T005250648234Z.json`；08:54为50/2,020 fetched、0 error，owner PID 29272。
- 10:06 `moneyflow`完成并独立审计PASS：2,020/2,020、4,841,995行、2010-01-05—2018-04-27、staging only。guardian已切换`margin_detail`；checkpoint=`margin_detail_20260801T020652430547Z.json`，10:08为50/2,006 fetched、0 error，owner PID 8532。
- 11:12 `margin_detail`完成并独立审计PASS：2,006/2,006、1,214,919行、2010-03-31—2018-06-29、staging only。guardian已切换`stk_limit`；checkpoint=`stk_limit_20260801T031210034429Z.json`，11:13为50/2,795 fetched、0 error，owner PID 28560。
- 12:45 `stk_limit`完成并独立审计PASS：2,795/2,795、6,484,477行、2007-01-04—2018-06-29、request-set hash=`802e17b3314d0b7578be60a9948fc298b06297735bd833f31d629868b93aaf40`、staging only。
- 当前精确断点：guardian PID 30808已切换到`stock_st`，owner PID 28700，checkpoint=`stock_st_20260801T044554149748Z.json`。最初请求返回`source_empty`；空响应不落盘且终态为INCOMPLETE，guardian最多重试两轮，随后审计失败关闭，禁止将空响应填零或误报完成。
- `stock_st`两轮结束并正式审计为`DATA_BLOCKED`：607任务中453 valid、154 missing，32,889行，实际可用范围2016-08-09—2018-06-29，request-set hash=`a6aef9499a4666cd01450ce69a5e124136b622047a07f3085e1fd65a22876644`。154个固定源空日期在审计文件逐项列出；首轮瞬时网络错误已在第二轮补齐，未发布生产库。
- guardian已增加并验证`-StartPhase`参数。当前精确断点为`financial`：长运行cell 794，owner PID 38528，checkpoint=`financial_20260801T053832415250Z.json`，13:40为43/6,555（42 fetched、1 source_empty）；该链完成后自动进入`index`和`event`。
- 14:04里程碑：同一`financial` checkpoint为675/6,555（10.30%；662 fetched、11 source_empty、2个可重试`ChunkedEncodingError`），锁、限流、分页和checkpoint均正常。继续守护cell 794，不得并行启动第二个Tushare进程。
- 14:28里程碑：同一`financial` checkpoint为1,325/6,555（20.21%；1,306 fetched、17 source_empty、2个可重试错误）；cell 794、owner PID 38528和全局锁持续健康。
- 14:51里程碑：同一`financial` checkpoint为2,000/6,555（30.51%；1,980 fetched、18 source_empty、2个可重试错误）；自20%以来无新增错误，继续守护cell 794。
- 15:13里程碑：同一`financial` checkpoint为2,625/6,555（40.05%；2,604 fetched、18 source_empty、3个可重试`ChunkedEncodingError`）；没有schema或分页契约错误，继续守护cell 794。
- 15:38里程碑：同一`financial` checkpoint为3,300/6,555（50.34%；3,277 fetched、18 source_empty、5个可重试`ChunkedEncodingError`）；错误类型仍只为瞬时传输中断，继续守护cell 794。
- 16:03里程碑：同一`financial` checkpoint为3,950/6,555（60.26%；3,924 fetched、21 source_empty、5个可重试错误）；自50%以来无新增错误，继续守护cell 794。
- 16:29里程碑：同一`financial` checkpoint为4,600/6,555（70.18%；4,568 fetched、27 source_empty、5个可重试错误、272,733行）；owner PID 38528、全局锁和checkpoint健康。当前工作树V6实跑51 passed，全仓收集1,613 tests。
- 16:55里程碑：同一`financial` checkpoint为5,275/6,555（80.47%；5,237 fetched、32 source_empty、6个可重试错误、314,412行）；70%—80%仅新增1个瞬时错误，唯一owner PID 38528和全局锁持续健康。
- 17:03后旧checkpoint停在5,490/6,555超过5分钟，30秒CPU仅增0.203秒，符合SDK长挂。已终止旧cell 794和owner PID 38528，核验锁PID/nonce后仅删除遗留锁；成功shard、sidecar和checkpoint全部保留。
- 17:10恢复为guardian cell 1057、owner PID 38488，checkpoint=`financial_20260801T091003975946Z.json`；17:11为427/6,555（419 cached、2 fetched、6 source_empty、0 error），继续跨越旧断点，禁止启动第二个Tushare进程。
- 17:25恢复轮到5,900/6,555（90.01%；5,625 cached、243 fetched、32 source_empty、0 error、352,106行），已跨越旧5,490断点；旧轮6个瞬时错误均已恢复，继续守护尾段。
- 17:48/17:53两次退出的根因均为`write_json_atomic`在Windows上遇到监视读取导致的瞬时`PermissionError [WinError 5]`，不是接口或schema失败；分片未损坏。现已对该异常增加10次×50ms有限重试并加测试，`test_tushare_backfill.py`为26 passed。
- 17:56修复后guardian cell 1092、owner PID 35272、checkpoint=`financial_20260801T095601171935Z.json`；17:57为425/6,555（419 cached、6 source_empty、0 error）。监控改为低频，禁止并发读取高频碰撞。
- 18:07 `financial`最终正式审计为`DATA_BLOCKED`：6,521/6,555 valid、34 missing、380,320行、75,971,414字节，request-set hash=`2004f9062c933caca7a970d0b09fe532afd41fa92b2a23c5ef0eef3ce032db73`。最终错误0；34个稳定源空任务完整列于`tushare_backfill_financial_v6.json`，未发布生产库。下一独立断点为`index`。
- 18:20 `index`正式审计为`DATA_BLOCKED`：256/259 valid、3 missing、115,738行、2002-01-04—2017-12-29，request-set hash=`a073805b34a3db4f232ed2f879ef9793b5c478f017d9b518b95da3beec5eb00a`。三个2016-01缺口分别属于`index_weight_000300_SH/000905_SH/000852_SH`；审计已增加dataset/API/request hash及全日期字段bounds。下一独立断点为`event`。
- 18:32 `event` checkpoint=`event_20260801T102344430104Z.json`为85/829（10.25%；21 fetched、64 source_empty、0 error），guardian cell 1132、owner PID 41076。任务分布：repurchase 212、stk_holdertrade 288、stk_holdernumber 317、pledge_detail 12；当前仍在repurchase早期月份。
- 18:37 `event`为175/829（21.11%；93 fetched、82 source_empty、0 error），已到repurchase 2015-06。最终汇总器会要求11个阶段审计齐全、staging-only、未发布且PASS/DATA_BLOCKED契约一致，否则状态为INCOMPLETE并禁止发布。
- 18:53 `event`为475/829（57.30%；319 fetched、156 source_empty、0 error），当前stk_holdertrade 2016-06；guardian/owner/锁未变化。
- 19:33 `event`正式审计为`DATA_BLOCKED`：645/829 valid、184 missing、228,429行，ann_date 1991-12-30—2026-06-11，request-set hash=`f6e64f69ebf894287e2272a5ce35a7847d952d4167a2cf8bbc04607e007b8415`，最终网络错误0。
- 最终Tushare汇总为`DATA_BLOCKED_PARTIAL`：11/11审计齐全、7 PASS、4 DATA_BLOCKED、43,222,321行、1,742,332,805字节；`tushare_backfill_v6_acceptance.{json,md}`已生成，生产发布被显式禁止。当前无Python下载进程、无全局锁、checkpoint `.tmp`为0。
- 最终代码验证：GOAL hash未漂移、三基线registry `--check` PASS、V6 54 passed、全仓1616 passed/0 skipped。`run_downside_beta_v6`完整复算审计PASS（554,400行、5,775股、96月、未来违规0），最终仍`REJECTED`。
