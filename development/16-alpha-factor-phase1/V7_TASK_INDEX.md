# V7子任务与leader任务书索引

所有任务必须先有独立、少于4000字符的leader任务书，再允许实现。历史诊断不构成新的独立确认。

| 顺序 | 子任务 | 类型/角色 | 启动门禁 | leader状态 | 执行状态 |
|---|---|---|---|---|---|
| 0 | V7公共协议 | 基础设施 | 无 | 已生成 | 已完成；19 tests |
| 1 | C7_CAPACITY_AWARE_QAV | independent_alpha | 公共协议通过 | 已生成 | Stage S有效；Stage P REJECTED；15节报告完成 |
| 2 | B7_LIQUIDITY_FRAGILITY | defensive | C7历史诊断完成 | 已生成 | Stage S REJECTED；Stage P未运行；15节报告完成 |
| 3 | F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION | benchmark_specific | B7历史诊断完成 | `V7_F7_CSI1000_INDUSTRY_EARNINGS_DIFFUSION_LEADER_BRIEF.md` | 财务审计通过；report_rc 0/100跨日补数；到数前验收完成 |
| 4 | E7_FUNDAMENTAL_CONFIRMED_RESIDUAL_MOMENTUM | independent_alpha | 首批三项完成 | 待生成 | 未开始 |
| 5 | J7_EARNINGS_REVISION_UNDERREACTION | independent_alpha | 数据审计通过 | 待生成 | 未开始 |
| 6 | G7_FIXED_60_20_20 | allocator | defensive及independent_alpha各至少一个合格 | 待生成 | 门禁关闭 |
| 7 | X7_A_F_HIERARCHICAL_CSI1000 | cross-lane | F7达到SHADOW | 待生成 | 门禁关闭 |
| 8 | X7_C_E_VALUE_WITH_CATALYST | cross-lane | C7/E7一项SHADOW、另一项SIGNAL_VALID | 待生成 | 门禁关闭 |
| 9 | X7_DEFENSIVE_FILTER_ALPHA | cross-lane | B7达到RISK_FILTER/SHADOW | 待生成 | 门禁关闭 |
| 10 | X7_F_C_HIERARCHICAL_FUNDAMENTAL | cross-lane | A+F、C+E之后 | 待生成 | 门禁关闭 |
| 11 | H7_INDEX_REBALANCE_FLOW | new alpha/event | 首批三项失败或第二批调度 | 待生成 | 未开始 |
| 12 | I7_SCHEDULED_SUPPLY_SHOCK | risk_filter/negative alpha | 数据审计通过 | 待生成 | 未开始 |
| 13 | K7_ANNOUNCEMENT_ATTENTION | new alpha/text | 可靠文本数据可得 | 待生成 | DATA_BLOCKED候选 |
| 14 | A7_UNCERTAINTY_AWARE_STACKING | index_enhancement | 第二阶段后 | 待生成 | 门禁关闭 |
| 15 | D7_NEW_FORCED_SELLING_EVENT | event alpha | 出现独立强制卖出机制 | 待生成 | 保持死亡 |

任务书生成时必须重新实测对应代码、数据、基线命令和白名单；不得把本索引当作实现规格。
