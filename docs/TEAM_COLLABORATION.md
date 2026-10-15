# 团队协作与任务拆分（历史M1/M2记录）

> **2026-10-15 交接说明：** 历史M1/M2协作快照。来源、控制台、多层Agent和两会话Memory已有后续实现；原任务分工、172测试数和F2继续实施语句均只属旧阶段。当前四业务完成后已停止，接手范围以最新用户指令和交接手册为准。
> [当前交接手册](../sujie/docs/PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

2026-10-14起的当前工作包见 [F2计划](../competition/docs/SUJIE_REVIEW_AND_PLAN_F2.md)、
[实施状态](../sujie/docs/F2_IMPLEMENTATION_STATUS.md)和
[官方能力证据](../sujie/docs/TOPIC5_EVIDENCE_MATRIX.md)。下文保留为早期工作记录，
不用于描述当前完成状态。已有用户授权的实施范围按F2推进。

## 先统一的项目口径

溯界不是“提示注入分类器”，而是 Agent 的运行时安全边界。检测结果是风险信号，真正阻断依靠任务授权、效果级策略和不可绕过的 MCP Tool Gateway。

当前可演示的是 M1：合法任务能够完成；Agent 读取含间接注入的告警后，即使提出越权读密钥和外发动作，网关也会阻断真实副作用并继续生成报告。确定性测试模型用于稳定触发危险提议，不代表真实 LLM 防御率。

## 当前基线

- M0：9 类 Schema、fixtures 和授权不变量已完成。
- M1：两个真实 stdio MCP Server、代理、三态决策、ASK 绑定与单次提交、Trace、Receiver Oracle 已完成。
- 本机完整检查历史记录为 172 passed；合并前以当前 CI 和本地重新运行结果为准。
- Ubuntu VM 已完成一次四容器双内部网络隔离验收；该记录不等于远端 CI 或生产部署证明。

## 推荐并行工作包

| 工作包 | 主要产物 | 合并前验收 |
|---|---|---|
| M2-A Artifact Registry | 内容 Hash、原文/规范化视图、父来源 | 改名、摘要、拼接不丢来源 |
| M2-B Propagation | authority、integrity、confidentiality、allowed_uses | 普通转换不能提权或降敏 |
| M2-C Exposure & Egress | exposure set、出口策略 | 敏感源经摘要/编码后仍不可外发 |
| M2-D Trace DAG | 图边、查询 API、最小可视化数据 | 能从违规动作追到触发源与经过节点 |
| Evaluation | clean/attack 成对样例、Oracle、报告格式 | 指标有分母、失败与超时分类 |
| Engineering | CI、容器、依赖与文档 | 可复现且不扩大 Agent 权限 |

开始 M3/M4 前，优先把 M2 的对象模型、传播不变量和 Egress 用例合并，避免不同分支各自定义不兼容的数据结构。

## 建议的首批 Issues

1. `M2: freeze Artifact and ProvenanceEnvelope invariants`
2. `M2: implement normalization span mapping and exposure set`
3. `M2: propagate labels across rename/base64/summary/concat`
4. `M2: enforce artifact-aware data.transfer policy`
5. `M2: expose trace DAG query with redacted payloads`
6. `Eval: define paired clean/attack case manifest and oracle schema`
7. `CI: add dependency and secret scanning without uploading test evidence`

每个 Issue 应包含：范围、明确不做什么、输入输出对象、测试 ID、验收命令、影响的信任边界和负责人。

## 合并节奏

- `main` 始终保持可运行；不直接向 `main` 推送功能提交。
- 小 PR 优先，Schema/接口先于调用方合并。
- 至少一名非作者 Review 安全语义；高风险边界变化要求两人确认。
- 每次里程碑结束更新 README 状态、验收记录、已知残余风险和真实命令输出。
