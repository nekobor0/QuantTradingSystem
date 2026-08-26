# 中国宏观数据用于量化因子与策略研究：方法论与工程规范 v0.1

**As of:** 2026-08-25
**用途:** 作为 Codex/Agent 构建中国宏观增量数据层、因子研究和策略研究的研究规范。
**配套文件:** `02_china_macro_data_universe_v0.1.yaml`

## 1. 核心结论

宏观数据更适合作为 **Macro State / Regime / Conditional Layer**，而不是简单把 GDP、PMI、M1 等当成普通横截面 Alpha 因子。

需要区分三件事：

1. **经济领先性**：某指标是否领先实体经济目标变量；
2. **信息领先性**：该指标在什么时候真实对市场参与者可得；
3. **收益预测性**：在信息可得之后，它是否仍能预测资产/因子未来收益。

三者不能混为一谈。PMI 可以领先工业生产，但股票市场可能在 PMI 公布前已经交易了同一信息，因此“领先经济”并不等于“领先股价”。

对低频 A 股量化，宏观层最有价值的典型用途是：

- Regime Classification；
- Conditional Alpha / Conditional Factor Efficacy；
- 因子/策略动态权重；
- Gross Exposure / Risk Overlay；
- Mixed-frequency Nowcasting；
- 宏观数据发布事件研究。

## 2. 宏观数据的主要维度

建议至少覆盖以下状态空间：

| Domain | 代表变量 | 主要研究问题 |
|---|---|---|
| Growth / Output | GDP、工业增加值、服务业、利润、用电、货运 | 经济增长处于扩张还是收缩？ |
| Survey / Expectations | PMI、新订单、新出口订单、预期 | 拐点是否正在形成？ |
| Consumption | 社零、餐饮、耐用品 | 居民需求强弱 |
| Investment | 固投、制造业、基建、高技术投资 | 资本开支周期 |
| Property | 投资、新开工、销售、房价、资金来源 | 地产信用-销售-投资链 |
| Inflation | CPI、核心CPI、PPI、购进价格 | 通胀/通缩及利润再分配 |
| Credit | M1/M2、贷款、社融及分项 | 信用扩张/收缩 |
| Liquidity / Rates | DR007、Shibor、政策利率、国债曲线、LPR | 资金价格与贴现率 |
| Fiscal | 收入、支出、土地收入、政府性基金 | 财政脉冲 |
| External | 出口、进口、贸易差额 | 外需周期 |
| FX / Capital Flow | 结售汇、涉外收付款、国际收支、外储 | 外部流动性与汇率压力 |
| Employment / Income | 调查失业率、收入、消费支出 | 居民资产负债表和就业周期 |
| Physical High-frequency | 用电、货运、港口、集装箱 | 低延迟实体经济代理 |
| Institutional | 社保等长期机构可见持仓 | 机构行为与公司质量信号 |

## 3. 领先、同步、滞后：必须相对于目标定义

对目标变量 `Y`，如果 `X_t` 对未来 `Y_{t+k}` 的解释力更强，可称 X 对该目标在该 horizon 下具有领先性：

```text
corr(X_t, Y_{t+k}) > corr(X_t, Y_t)
```

如果主要反映当期状态，则是同步；如果在经济活动发生后才确认，则偏滞后。

典型经济链：

```text
订单/信用 -> 生产/销售 -> 收入 -> 利润 -> 税收/部分就业指标
```

因此，常见经验分类大致是：

- **领先**：PMI新订单、新出口订单、信用脉冲、企业中长期贷款、部分价格/利率预期、地产销售/新开工；
- **同步**：工业增加值、PMI生产、发电量、货运量、社零；
- **滞后**：工业利润、税收、部分就业、企业财务利润。

但这只是经济结构上的先验。进入量化研究后，必须对每一个 `target × horizon` 单独检验。

## 4. 为什么“领先经济”不等于“预测股票”

一种常见时序是：

```text
股票/商品/利率先交易预期 -> PMI改善 -> 工业生产改善 -> GDP确认
```

此时 PMI 对 GDP 是领先指标，但对股票收益可能没有预测力，甚至是滞后的。

所以研究时应拆成：

```text
EconomicLead(X -> macro target)
InformationLead(release_ts)
ReturnPredictability(X -> future return)
```

不能因一个宏观指标有“先行指标”标签，就直接把它纳入交易模型。

## 5. Point-in-Time：宏观回测最重要的工程要求

每条观测至少保存四个时间字段：

```text
observation_period   # 数据描述的经济时期
release_ts           # 官方实际发布时间
available_ts         # 策略在工程上最早允许使用的时间
vintage_ts           # 这一版本数值的版本时间/抓取版本
```

严格规则：

```text
feature can be used at t  iff  available_ts <= decision_ts(t)
```

例如 12 月工业增加值即使属于 `2025-12`，如果在 2026-01-19 10:00 发布，那么 1 月 1 日到 1 月 19 日 10:00 前的决策都不能使用该值。

### 5.1 Release Date 与数据库更新时间不是一回事

国家统计局 2026 年发布日程明确说明，“国家数据”数据库通常在数据发布后约 **3 个工作日**更新全部进度指标。工程上因此建议：

- 发布稿/发布日程：提供 `release_ts`；
- 国家数据：提供结构化历史数值；
- 两者用 `series_id + period` 做配对。

不要用数据库页面最后更新时间代替经济数据的真实首次公开时间。

### 5.2 盘中发布时间

如果策略只在收盘后/次日开盘交易，可定义：

```text
available_ts = next_tradable_bar_after(release_ts)
```

如果做事件研究，则必须保存分钟级甚至秒级发布时间，并明确：

- 发布前窗口；
- 发布后 5m / 30m / 1d；
- 当天是否已开盘；
- 节假日和非交易日处理。

## 6. Revision / Vintage 风险

很多宏观数据会被修订或因统计制度调整而改变历史值。用 2026 年下载的最终历史值回测 2010 年策略，可能造成 **revision look-ahead bias**。

建议数据层区分：

```text
macro_raw      # 官方原始观测
macro_vintage  # 每次发布/修订的版本
macro_feature  # 只基于当时可得vintage的派生特征
```

如果历史 vintage 无法重建：

```text
vintage_status = unavailable
research_grade = exploratory_only
```

不要假装拥有实时历史。

## 7. 更高频的数据是否一定更有利？

不是。

高频化同时增加：

- 信息容量；
- 噪声；
- 微观结构效应；
- 多重检验自由度；
- 交易成本；
- 数据缺失与异常值；
- 模型过拟合概率。

因此不存在：

```text
HigherFrequency => HigherAlpha
```

更合理的是衡量 **有效信息率**：新信息增量是否超过噪声与实施成本。

对低频 A 股体系的建议：

- 月度：宏观研究核心频率；
- 周度：产业/流动性补充；
- 日度：利率、汇率、市场流动性、风险状态；
- 分钟/Tick：只在明确做宏观公告事件研究时引入。

## 8. 高频真正的价值：Nowcasting，而不是“频率本身”

季度 GDP 很慢，但可以用更快的 PMI、用电、货运、港口、商品等估计当前经济状态：

```text
Nowcast(GDP_t) = f(PMI_t, electricity_t, freight_t, credit_t, trade_t, ...)
```

可使用：

- Dynamic Factor Model；
- Kalman Filter；
- MIDAS；
- Bayesian mixed-frequency model；
- 正则化线性模型作为简单基准。

评估重点不是 in-sample R²，而是 **real-time vintage 下的 out-of-sample nowcast error**。

## 9. 推荐的宏观研究方式

### 9.1 不建议：宏观变量大规模裸挖 Alpha

```text
3000 macro features -> test future returns -> keep p<0.05
```

中国月度样本从 2000 到 2026 也只有约 320 个观测；宏观序列高度自相关且彼此共线，大规模裸筛极易产生 data mining bias。

### 9.2 建议：先构造经济状态

可先构建五个 latent state：

```text
MacroState_t = (
    Growth_t,
    Inflation_t,
    Credit_t,
    Liquidity_t,
    External_t
)
```

再研究：

```text
E[FactorReturn_k,t+1 | MacroState_t]
```

例如比较红利、价值、质量、小盘、动量、低波在不同宏观状态下的条件收益、胜率、回撤和容量。

### 9.3 因子权重条件化

基础模型：

```text
Score_i = wV*Value_i + wM*Momentum_i + wQ*Quality_i + wS*Size_i
```

改造成：

```text
w_k,t = f(MacroState_t)
```

这里宏观层不是和个股 Alpha 竞争，而是估计 **哪个 Alpha 在当前状态更可能有效**。

### 9.4 Risk Overlay

宏观状态也可以只影响仓位：

```text
GrossExposure_t = f(Credit, Liquidity, Growth, Volatility, Trend)
```

避免把弱宏观预测信号直接强制映射为个股选择。

## 10. Level / Change / Acceleration

市场通常更关心边际变化，而不是绝对水平。对一个增长指标 G：

```text
Level_t        = G_t
Change_t       = G_t - G_{t-1}
Acceleration_t = Change_t - Change_{t-1}
```

宏观研究至少同时生成：

- level；
- YoY / MoM / QoQ；
- change；
- acceleration；
- rolling z-score；
- expanding/rolling percentile；
- 3m/6m moving average；
- surprise（如有实时一致预期）。

注意：历史分位数必须用 expanding/rolling window，禁止用 2000-2026 全样本分位数反向赋给 2005 年。

## 11. 累计值是中国宏观数据的特殊工程问题

固定资产投资、财政、地产、工业利润等大量指标以年初至今累计值发布。

常见做法：

```text
single_month_t = YTD_t - YTD_{t-1}
```

但不能机械应用到所有数据。国家统计局明确解释过，发电量等工业统计中，由于企业名录范围变化和累计值重新核实，累计数据不一定等于各月值简单相加。

因此每个序列要有：

```text
cumulative_to_single_month_allowed: true/false/conditional
```

并写单独单元测试。

## 12. 数据源与长期历史策略

### 12.1 国家统计局

核心来源：

- 国家数据：`https://data.stats.gov.cn/easyquery.htm`
- 发布日程：`https://www.stats.gov.cn/xxgk/sjfb/fbrcb/`

适合：GDP、工业、消费、投资、地产、CPI/PPI、PMI、就业等。

国家数据包含月度、季度、年度等数据库。对于 2000-2005 及更早，长期核心序列通常优先从这里探测；但必须核对统计制度变化。

### 12.2 中国人民银行

适合：M0/M1/M2、贷款、存款、社融、金融市场统计、政策工具。

社融的关键历史事实：

- 2011 年正式编制并公开社融增量统计；
- 官方历史表可回溯至 2002 年；
- 2015 年正式发布 2002-2014 社融存量历史数据；
- 后续构成和金融统计范围多次变化。

所以社融适合做长周期研究，但必须版本化口径。

### 12.3 财政部

`https://www.mof.gov.cn/gkml/caizhengshuju/`

适合：一般公共预算收入/支出、税种、政府性基金、土地出让等。多为累计值，发布时间并非严格固定。

### 12.4 海关总署

`https://stats.customs.gov.cn/`

官方海关统计在线查询平台可按商品、贸易伙伴、贸易方式等维度查询。平台在 2018 年上线；对于更早数据，需要结合历史月报/年鉴/归档页面获取，并保存 HS 版本映射。

### 12.5 国家外汇管理局

SAFE 每年发布主要统计数据发布时间表，适合建立严格 PIT。

重要制度点：

- 国际收支初步数自 2009 年 8 月起增加发布；
- 服务贸易数据自 2014 年起按月公布；
- 货物贸易数据自 2015 年起按月公布；
- 全口径银行结售汇自 2013 年起按月公布，更早为银行代客口径。

### 12.6 国家能源局 / 交通运输部

适合作为低延迟实体经济代理：

- 全社会用电；
- 分产业用电；
- 营业性货运；
- 港口吞吐；
- 集装箱；
- 交通固定资产投资。

长期历史的制度连续性弱于 NBS/PBOC 核心宏观，需先做数据质量审计。

## 13. 社保基金调仓数据：到底是什么频率？

需要区分两套完全不同的数据。

### 13.1 全国社保基金会自己公开的数据

全国社会保障基金理事会官方年度报告至少从 **2001 年**开始可查。

投资管理制度要求：

- 每年一次向社会公布基金资产、收益等财务状况；
- 每季度向财政部、人力资源社会保障部门提交财务会计报告、投资管理报告。

但后者不是面向公众完整披露的季度股票组合。

因此，不能从社保基金会官网直接获得“每季度完整买卖了哪些 A 股”。

### 13.2 市场数据库里的“社保基金持仓”

常见的社保持仓/调仓数据，本质上是从上市公司定期报告中的主要股东/流通股东信息反向重建：

```text
上市公司报告 -> 识别“全国社保基金XXX组合” -> 季度末持仓快照 -> 前后期比较
```

建议研究主样本从 **2004Q3 左右**开始，因为此后前十大流通股股东的季度披露更稳定；2003-2004 的零散记录可以回溯，但不宜和后期视为完全同质。

### 13.3 “季度频率”不等于“季度末即可交易”

例如：

```text
observation_end = 2025-03-31
filing_ts       = 2025-04-28 20:00
```

那么：

```text
available_ts = 2025-04-28 20:00 或下一个可交易bar
```

4 月 1 日绝不能使用这份 3 月 31 日持仓快照。

### 13.4 区间删失与可见性偏差

如果某社保组合从第 10 大股东降为第 11 大股东：

```text
15m shares -> 14m shares
```

公开数据可能表现为：

```text
15m -> missing
```

不能解释为：

```text
15m -> 0
```

所以社保持仓是 **censored holdings dataset**。必须建立：

```text
visibility_state = observable / censored / unknown
```

同理：

- 新进入前十大 ≠ 本季度首次买入；
- 退出前十大 ≠ 清仓；
- 两期都可见时，才适合直接计算可见持股变化。

### 13.5 更合理的社保因子

比单一 `new_entry` 更值得测试的包括：

```text
NSSFConsensus       = 同股可见社保组合数量
NSSFPersistence     = 连续可见季度数
NSSFVisibleChange   = 两期均可见时持股变化
NSSF x Quality      = 社保信号与盈利质量交互
NSSF x LowCrowding  = 社保信号与低公募拥挤交互
```

这些仍然必须以报告披露日为信号时间。

## 14. 推荐数据库 Schema

### macro_raw

```yaml
series_id:
observation_start:
observation_end:
period_label:
value:
unit:
seasonal_adjustment:
preliminary:
methodology_version:
source_url:
raw_hash:
```

### macro_vintage

```yaml
series_id:
observation_end:
release_ts:
available_ts:
vintage_ts:
value:
revision_seq:
source_url:
fetched_at:
```

### macro_feature

```yaml
feature_id:
series_id:
asof_ts:
value:
transform_version:
lookback:
source_vintage_cutoff:
```

### macro_regime

```yaml
asof_ts:
growth_state:
inflation_state:
credit_state:
liquidity_state:
external_state:
model_version:
training_end_ts:
```

## 15. Codex 增量采集建议

每个 source adapter 至少完成：

```text
list_series()
fetch_history(series_id, start, end)
fetch_latest(series_id)
parse_release_timestamp(raw)
parse_methodology_notes(raw)
normalize(raw)
validate(normalized)
persist_raw(raw)
persist_vintage(normalized)
```

### 抓取优先级

```text
官方结构化接口 / XLS / CSV
    > HTML table
    > 官方PDF文本层
    > OCR
```

### 每次抓取保存

```text
source_url
request_params
fetched_at
http_status
content_hash
parser_version
raw_file_path
```

这样网站改版后仍能重放旧解析器或重新解析 raw snapshot。

## 16. Research Harness 建议

### 第一步：验证“宏观状态”，不要先验证“股票收益”

例如先看：

```text
PMI_new_orders_t -> industrial_VA_{t+1,t+2}
CreditImpulse_t  -> property_sales / industrial_profit
PPI_input_t      -> PPI_t+1
```

如果经济链本身都不稳定，就不应直接进入资产预测。

### 第二步：测试资产条件效应

```text
FactorReturn_{k,t+1} = alpha + beta * MacroState_t + epsilon
```

或直接做 regime-conditioned distribution：

```text
mean / median / win_rate / drawdown / tail_loss
```

### 第三步：走样本外

宏观样本非常少，默认：

```text
expanding-window walk-forward
```

避免随机 K-fold。

必要时对模型复杂度施加强约束：

- 少参数；
- 强正则；
- 稳定性筛选；
- 多定义敏感性；
- 多重检验控制；
- 经济机制先验。

## 17. v0.1 的实施顺序

### P0：数据治理

先完成：

- source registry；
- raw/vintage schema；
- 时间戳语义；
- content hash；
- parser version；
- methodology break registry。

### P1：核心 T1

优先：

```text
PMI
Industrial VA
CPI/PPI
M1/M2
Loans
TSF
DR007/Shibor
Government yields
FAI
Property sales/investment
Exports/imports
Fiscal revenue/expenditure
```

### P2：Nowcast / T2

加入：

```text
PMI细分
用电
货运
港口
细分消费
细分投资
跨境资金流
```

### P3：机构数据

最后构建：

```text
NSSF annual
NSSF quarterly visible holdings
visibility/censoring state machine
```

## 18. 验收标准

一条生产级宏观序列至少通过：

1. `first_non_null` 和 `last_non_null` 可解释；
2. 历史缺失率、重复值、异常跳点已统计；
3. 至少 5 个历史时点与官方原文核对；
4. `release_ts` 有来源；
5. 口径变化有 `methodology_version`；
6. 修订风险有标记；
7. 派生因子只读取当时可得 vintage；
8. 截至当前的最新官方值能与采集结果一致；
9. 单元测试覆盖累计转单月、节假日、非交易时间发布；
10. 研究结果能从 raw snapshot 完整重放。

## 19. 官方来源核验要点（截至 2026-08-25）

- 国家统计局“国家数据”提供月度、季度、年度等数据库；2026发布日程明确数据库通常在正式发布后约3个工作日更新全部进度指标。
- 国家统计局说明制造业、非制造业采购经理调查分别于2005年、2007年纳入国家统计调查制度；综合PMI公开发布前进行了2016-2017试算。
- 全国城镇调查失业率自2018年起正式按月对外发布；劳动力调查制度本身更早存在。
- 现行70城住宅销售价格统计方法自2011年1月起实施；2026年又发生新一轮对比基期调整。
- 人民银行官方材料显示社会融资规模增量2011年正式编制公布，历史数据可回溯到2002年；2015年发布2002-2014存量历史数据。
- Shibor自2007-01-04正式运行；LPR存在2013旧机制与2019-08改革后的明显制度断点。
- SAFE 2026发布时间表确认国际收支、结售汇、涉外收付款等系列的发布频率及若干历史制度起点。
- 全国社保基金年度报告至少从2001年可查；制度要求年度公开财务状况、季度向主管部门报告，但公众看到的A股“社保持仓”主要来自上市公司定期报告重建。

## 20. 与配套 YAML 的关系

本文负责：

```text
why / research rules / PIT rules / validation rules
```

`02_china_macro_data_universe_v0.1.yaml` 负责：

```text
what to collect / where / how / history target / release rule / breakpoints / suggested features
```

Agent 实施时应将 YAML 视为 **数据目录与 backlog**，将本文视为 **不可违反的研究约束**。
