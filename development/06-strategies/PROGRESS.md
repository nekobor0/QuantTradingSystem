# strategies 开发进度

- 目标：同时实现隔离、可复现的 ETF 择时和个股日频选股运行。
- 顺序：定义/状态 → ETF 门控/调仓 → 个股评分/变化 → 解释/证据 → 双仓储/DDL → 验收。
- 最大风险：双策略用途串用，或空结果被误解释为现金门控。
- 任务 0：完成；上游 375 passed、strategies 0；06 文档 SHA256 `4472D9648109A828978A4553E58D386545FA271EA54365FE3FAD73A28A09F038`，其余保护指纹一致；旧策略层 17 文件且存在填 0/空结果成功/动态 IC 入口，不直接迁移。
- 任务 1：完成；状态机、ETF 日频门控/周度调仓/非调仓保持/风险退出和显式 cash gate 已实现。
- 任务 2：完成；个股两日 SELECT/KEEP/EXIT、贡献解释、资格排除、幂等与显式 supersede 已实现。
- 任务 3：完成；研究证据隔离、内存/SQLAlchemy 双仓储、PostgreSQL DDL 与 93 项模块测试通过。
- 反向验证：临时把无候选 ETF 的 `cash_gate` 强制为 false，两套仓储黄金测试均失败（exit 1）；已恢复。
- 验收：前六模块组合 468 passed、0 skipped；mypy 51 files clean；compileall、文档校验均 exit 0；受保护指纹一致。
- 状态：完成。
