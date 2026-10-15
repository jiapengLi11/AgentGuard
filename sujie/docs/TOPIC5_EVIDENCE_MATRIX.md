# 题目5：要求—实现—证据矩阵

更新：2026-10-15，截至M21。官方依据是[2026-10-14题目快照](../../competition/research/2026-10-14/topic5-official.json)，原始SHA-256 `d758dfe33aa17ce023d8538381d93bdb619fe2ad69fdbcc9593264b315360368`。本轮为文档交接，没有重新核验赛事通知，提交前应核对官方最新信息。

[已完成汇总](COMPLETED_WORK_SUMMARY.md) · [运行/代码/证据手册](PROJECT_HANDOFF.md) · [W0–W9状态](F2_IMPLEMENTATION_STATUS.md)

## 官方能力与实际支持

| 要求 | 已有实现和阶段证据 | 剩余缺口 |
|---|---|---|
| 1：直接/间接/Memory注入识别 | M11可信补充输入不扩权、MCP正文/元数据规则；M18两实际会话恢复来源并重新检测Memory | 三入口全路径、更多隐性触发/检索和完整执行矩阵，W1/W4/W7 |
| 2：原始意图/计划/全工具序列 | [M13](M13_SEQUENCE_AND_TEMPORAL_SOURCES.md)可信目标、可见提议、全记录工具提议、来源、实际效果/UNKNOWN及请求回复关联 | 跨轮/组合语义、分级检测与更多任务；可见计划不含隐藏思维，W2 |
| 3：语义DSL与三态 | Contract/Grant、效果适配、DSL、ALLOW/ASK/BLOCK；IOC/Git自主审批、执行前复核 | 五效果完整目标矩阵与更广部署，W3/W5 |
| 敏感目录写入 | 逻辑路径/工作区写授权及边界/逃逸测试 | 各敏感目录/平台实际目标矩阵与系统级验收 |
| 敏感网络外发 | [M14](M14_NETWORK_AND_WEB_WORKFLOW.md)真实封闭GET/POST，目标/重定向/header/body/来源检查；M4来源消融 | 公开HTTPS/新隔离拓扑、更广合法请求及任意分片改写DLP |
| 编码/下载执行 | [M15](M15_STRUCTURED_EXECUTION_AND_ARTIFACT.md)注册程序、argv/摘要绑定、拒绝解释、真实子进程/收据 | 通用OS沙箱、进程树/资源限制/跨平台矩阵 |
| 检视下Git推送 | [M16](M16_GIT_DELIVERY_AND_APPROVAL.md)实际封闭Git交付，确切remote/ref/commit/旧值/配置/lease；检视拒绝/授权ASK | 任意外部Git服务、不可信仓库与当前Linux隔离 |
| 敏感委派 | [M17](M17_ACTUAL_ANALYTICAL_AGENTS.md)秘密输入创建前拒绝、只读子/孙对话，资源/权限/预算收窄、父撤销 | 更多完整性攻击形态与跨进程隔离 |
| 4：多MCP/多层Agent | M17三个实际对话/两MCP，主体/父子/深度与来源交接；M18两实际会话/版本原文 | 同Host非OS隔离；更完整可视化时序和受控正文访问，W4/W9 |
| token来源/DAG/参数返回/影响 | [M11](M11_CONTEXT_EGRESS.md)本地固定tokenizer、字面/JSON转义；M13前缀/回复绑定；Trace/DAG、文件/网络/Git/Memory状态 | 全入口/转换/完整有效请求和返回证据；本地token不等于云内部token，W1/W9 |
| 5：七类绕过及语言 | 有界规范化、部分Unicode/编码/分片/语义伪装等开发变体；M4/M5/M9/M10 | 中英日俄/Emoji、Unicode、分片多轮、注释分隔符、格式编码、上下文稀释、语义伪装完整覆盖与独立执行，W7 |

## 业务与实验支持（不是额外官方硬条件）

- [M19](M19_COMMON_RUNTIME_AND_BASELINES.md)：共同5配置和2消融，35强制提议单元/45脚本业务校准；云7/10完成。3次IOC失败未提发送/BLOCK0，不归因来源机制。公共执行器/Provider保障不计为Full独有贡献。
- [M20](M20_VERIFIED_EVIDENCE_QUOTATIONS.md)：report有界无工具分析，Host字面核对/位置/未引用区间；语义标签为建议，保留原限制。脚本主流程+云分析1请求353tokens，不是完整W6或自主云任务。
- [M21](M21_FOUR_BUSINESS_WORKFLOWS.md)：四个多源业务实际MCP/读取/事实/完整性Oracle，当前13开发profile；最终16脚本运行完成。四云首轮3/4，时间线修复后单独完成，跨版不合并成功率。正式独立任务登记、C/A/Q/R五配置主比较和聚类统计仍待完成。
- 当前控制面主/子/Memory及正文分析角色有ProtectedModel/共享预算；历史分类/独立评测入口和完整有效请求尚未全部统一。
- 当前无可用Linux环境，新版整体隔离与性能待验收；历史M1容器不替代新版。Java/MySQL、12/60任务、200案例、288内部运行和延迟目标均为内部设计选择，不是题目新增要求或已有成绩。

**F3整体未完成；用户要求完成四类业务后停止已执行。本轮只更新文档，后续工作未恢复。**
