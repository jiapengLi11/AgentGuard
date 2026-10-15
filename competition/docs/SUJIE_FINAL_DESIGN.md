# 溯界（Sujie）比赛版最终设计基线

> **2026-10-15 交接说明：** 目标设计基线，保留原方案，不代表全部已交付。实际控制面改用Python，Java/MySQL未实现；网络/注册进程/Git/真实子孙/两会话Memory及四业务见M14–M21。原60任务/200案例/七周路线是内部目标，非官方条件。当前实现与剩余工作以交接手册/状态为准。
> [当前交接手册](../../sujie/docs/PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

版本：F1.0
状态：历史 F1.0 基线。2026-10-14 起，排期、阶段范围和内部规模目标由
[F2 复盘与实施计划](SUJIE_REVIEW_AND_PLAN_F2.md)取代；当前推进按[F3计划](SUJIE_REVIEW_AND_PLAN_F3.md)。历史验收与实验按原版本保留。
适用赛题：揭榜挑战赛题目5——面向大模型智能体提示注入与工具滥用的检测防御技术
产品类别：大模型智能体运行时安全网关平台

> 一句话定义：溯界部署在 Agent Host 与 MCP/本地工具之间，以可信任务契约冻结授权边界，以来源—用途信封约束不可信内容的传播与使用，以效果级执行闸门实施 ALLOW / ASK / BLOCK，并生成跨 MCP、子 Agent、记忆的可验证攻击链。

---

## 0. 冻结规则

本文件是比赛版架构的唯一事实来源（source of truth）。实现 Agent 不得自行替换主线、增加未经评审的“创新名词”或删除赛题必选能力。

允许调整：

- 类名、包名、界面布局和不影响安全语义的实现细节；
- 依赖库的小版本；
- 测试数量在不低于最低验收规模的前提下增加。

必须先提交 ADR/RFC 并由项目负责人确认后才能调整：

- 信任边界；
- TaskContract、ProvenanceEnvelope、SemanticAction 的字段和不变量；
- 三态决策语义；
- 默认拒绝和用户确认规则；
- 数据面/控制面边界；
- 验收指标口径；
- P0 范围。

---

## 1. 产品定位与差异化

### 1.1 最终开发物

最终交付的是一套可用 Docker Compose 启动的软件系统，由以下部分组成：

1. Python 安全数据面：Host Hook、MCP Proxy、内容检测、来源传播、策略决策、工具适配与执行闸门。
2. Spring Boot 控制面：任务、策略、审批、告警、审计和系统配置 API。
3. Vue 3 控制台：攻击告警、三态审批、来源 DAG、调用时序和影响范围。
4. LangGraph 演示 Agent：可读取外部内容、调用工具、写入记忆并派发子 Agent。
5. 两个以上真实 MCP Server 与封闭靶场：文件/记忆服务、网络/命令/Git/派发服务、恶意 MCP 变体、测试接收端和本地 Git 远端。
6. 自动评测程序、测试集、部署文档、设计文档和测试报告。

它不是：

- 只有一个提示注入分类器；
- 依靠另一个 LLM 决定一切的“安全 Agent”；
- 重新实现 Cursor/Claude Code；
- 只做前端展示的普通 App；
- 对任意第三方远程 MCP 内部行为提供保证的通用沙箱。

### 1.2 贡献口径

不宣称任务授权、污点传播、策略 DSL、三态审批、运行时网关或提交复核本身是首创。

比赛版争取形成三项组合贡献：

1. **来源—用途约束**：不可信证据可被分析、引用和受控存档，但不能经摘要、记忆、子 Agent 或工具返回升级为执行授权。
2. **攻击后的安全任务持续执行**：阻断越权副作用后，不简单终止任务，而是通过结构化安全异常和证据隔离路径继续完成原始研判。
3. **效果级工程闭环**：对真实工具参数、来源依赖、任务授权和执行状态做统一判断，以真实文件、网络、进程、Git、记忆副作用作为安全 Oracle。

正式答辩表述：这是面向安全研判 Agent 的运行时防护机制组合与工程验证，不把已有单项技术重新命名为原创算法。

### 1.3 特色演示主线

用户要求分析一份包含危险命令的告警附件并生成报告：

- 系统允许读取并解释攻击内容；
- 攻击内容中的“读取凭据并外发”不能成为 Agent 指令；
- 越权工具调用被阻断；
- Agent 获得不含秘密的结构化安全异常后重新规划；
- 报告仍生成，危险命令仅作为引用证据；
- 控制台展示攻击来源、传播路径、阻断点和最终业务结果。

---

## 2. 威胁模型

### 2.1 保护目标

- 机密性：合成密钥、凭据、敏感文件和会话敏感数据不得流向未授权目的地。
- 完整性：外部内容、工具描述、工具返回、记忆和子 Agent 输出不得升级为授权或篡改可信任务边界。
- 授权一致性：执行动作必须属于用户身份权限、当前 TaskContract 与有效 TaskGrant 的交集。
- 可追溯性：每个关键动作能够关联来源、转换、主体、工具、策略、审批、结果和影响对象。
- 可用性：防御不应通过“全部拒绝”获得安全指标；合法任务和危险证据分析任务必须可完成。

### 2.2 攻击者能力

| 攻击者 | 可控制内容 | 不应能够控制 |
|---|---|---|
| 恶意普通用户 | 用户消息、多轮拆分、角色伪装、编码混淆 | 系统策略、认证身份、控制面审批记录 |
| 外部内容攻击者 | 网页、文档、源码注释、工单、邮件、PDF解析文本 | TaskContract、TaskGrant、执行凭据 |
| 恶意 MCP Server | 工具名/描述/Schema、返回字段、注册版本、受控靶场内实现 | 网关策略、其他 Server 凭据、宿主网络权限 |
| 记忆污染者 | 被写入和后续检索的记忆正文 | 记忆来源元数据、授权状态 |
| 被劫持子 Agent | 子任务输出、工具提议、传回文本 | 父任务以上权限、控制面确认 |

### 2.3 可信计算基

可信：

- 认证与审批入口；
- 策略及其签名版本；
- TaskContract/TaskGrant 服务；
- Host Adapter 与 MCP Proxy；
- Provenance Store；
- 受信任的 Effect Adapter；
- 受控执行器和网络出口代理。

不可信：

- 所有模型输出；
- 普通文本中的“管理员已批准”等声明；
- 外部资源正文；
- MCP 工具描述和返回；
- 记忆正文；
- 子 Agent 输出；
- 语义检测器给出的 ALLOW 建议。

### 2.4 不可绕过部署约束

比赛靶场中的 Agent Host 必须满足：

- 不持有工具执行凭据；
- 默认不能直接访问宿主文件系统、Docker Socket 和外部网络；
- 所有敏感工具只能通过 Gateway/受控执行器；
- 子 Agent 继承相同限制；
- 模型 API、最终回复、日志预览同样视为数据出口；
- 网关故障时，高风险写操作 Fail-closed；低风险只读是否降级由策略明确配置。

### 2.5 明确不保证

- 不保证提示注入零漏报、零误报；
- 不防御宿主内核、管理员或全部可信控制面失陷；
- 不验证任意远程 MCP Server 的内部真实行为；
- 不承诺撤回已经外发的数据；
- 不承诺任意 Shell 语义等价判断；
- 不将本地来源图表述为模型内部因果链；
- 不将远程 API 调用伪装成可回滚事务。

---

## 3. 总体架构

### 3.1 热路径

```text
User -> Agent Host -> Host Adapter/MCP Proxy -> Security Data Plane
     -> Effect Adapter -> Controlled Executor/MCP Server
     -> Security Data Plane -> Agent Host
```

安全数据面包含：

- Task Contract Cache；
- Tool Registry Guard；
- Content Intake & Normalizer；
- Prompt Injection Detector；
- Provenance Engine；
- Semantic Action Mapper；
- Policy Decision Point；
- Approval/Commit Gate；
- Trace Emitter。

### 3.2 控制面不进入实时热路径

Spring Boot 控制面负责：

- 用户、角色和任务管理；
- 策略增删改查与版本发布；
- TaskContract 审核和版本记录；
- ASK 审批；
- 告警、审计和证据查询；
- 性能与安全统计。

数据面在内存中使用已签名/带 Hash 的策略与合同快照。普通工具调用不得同步查询 MySQL。审计事件批量异步上报；审批和合同变更才同步访问控制面。

### 3.3 技术栈冻结

- 数据面：Python 3.12、FastAPI/Pydantic、官方 MCP Python SDK 固定版本。
- 演示 Agent：LangGraph，模型接口可替换。
- 控制面：Java 21、Spring Boot 3、MyBatis-Plus 或 Spring Data JPA 二选一后锁定、MySQL 8。
- 前端：Vue 3、TypeScript、Element Plus、ECharts。
- 部署：Docker Compose；首版不引入 Kubernetes、Kafka、微服务拆分。
- 缓存：数据面进程内缓存；Redis 仅在确有多实例需求后作为 P1，不是 P0。
- 观测：结构化 JSON 事件；可选 OpenTelemetry，不作为 P0 阻塞项。

---

## 4. 六个核心数据对象

所有对象使用 UUIDv7/ULID，时间统一 UTC，序列化使用版本化 JSON Schema。

### 4.1 TaskContract

```json
{
  "schema_version": "1.0",
  "contract_id": "ctr_...",
  "version": 1,
  "principal_id": "user_...",
  "session_id": "ses_...",
  "trusted_goal": "分析工作区中的告警附件并生成本地报告",
  "workspace_roots": ["/workspace/case-001"],
  "allowed_purposes": ["READ", "ANALYZE", "QUOTE", "WRITE_REPORT"],
  "allowed_effects": [
    {"kind": "file.read", "resource": "/workspace/case-001/**"},
    {"kind": "file.write", "resource": "/workspace/case-001/output/**"}
  ],
  "forbidden_effects": ["credential.read", "external.data_transfer", "git.push"],
  "budgets": {"tool_calls": 40, "network_calls": 5, "subagents": 2},
  "expires_at": "...",
  "parent_contract_id": null,
  "policy_snapshot_hash": "sha256:...",
  "status": "ACTIVE"
}
```

生成规则：

1. Trusted Intent Compiler 只读取认证用户的原始任务、系统策略、用户角色权限和工具效果目录；不读取随后获取的外部证据。
2. LLM 可以生成合同草案，但合同权限上限由确定性 Capability Baseline 裁剪。
3. 不明确的高风险副作用不自动加入合同。
4. 外部内容、记忆或子 Agent 不能修改合同。
5. 扩权必须由真实用户在控制面确认，生成新版本；旧版本不可原地覆盖。

### 4.2 TaskGrant

TaskGrant 是面向主体和子任务的短期能力租约：

```json
{
  "grant_id": "grt_...",
  "contract_id": "ctr_...",
  "subject_id": "agent_main",
  "parent_grant_id": null,
  "effects": ["file.read", "file.write:report"],
  "resource_scopes": ["/workspace/case-001/**"],
  "budgets": {"tool_calls": 20},
  "expires_at": "...",
  "status": "ACTIVE"
}
```

子 Agent 权限不变量：

```text
Grant(child) ⊆ Grant(parent) ∩ Need(child) ∩ Contract
```

### 4.3 ProvenanceEnvelope

```json
{
  "artifact_id": "art_...",
  "content_ref": "evidence://...",
  "content_hash": "sha256:...",
  "origin": {
    "type": "MCP_TOOL_RESULT",
    "source_id": "srv_web/search",
    "event_id": "evt_..."
  },
  "authority": "DATA_ONLY",
  "integrity": "UNTRUSTED",
  "confidentiality": "PUBLIC",
  "allowed_uses": ["READ", "ANALYZE", "QUOTE", "STORE_EVIDENCE"],
  "forbidden_uses": ["AUTHORIZE", "EXECUTE", "CHANGE_POLICY"],
  "parents": ["art_parent"],
  "transformations": [
    {"type": "UNICODE_NFKC_VIEW", "version": "1", "mapping_ref": "map://..."}
  ],
  "source_spans": [
    {"source_start": 10, "source_end": 80, "view_start": 10, "view_end": 75}
  ],
  "created_at": "..."
}
```

传播不变量：

1. 普通模型转换不能提高 authority 或 integrity。
2. 派生物 confidentiality 取父输入最高等级，除非经过白名单可信脱敏器。
3. 确定性复制、切片、解码保留区间映射；摘要/自由改写仅保留父集合和保守依赖，不伪造 token 因果。
4. 对进入同一模型上下文的输入建立 exposure set；自由文本输出保守继承该集合。
5. allowed_uses 默认取相关父输入用途的交集；结构化字段可基于字段级依赖单独计算。
6. Artifact 名称、重新编码、摘要和跨 Agent 传递不清除来源。

### 4.4 SemanticAction

工具名称不能直接作为策略语义。Effect Adapter 将物化调用转换为：

```json
{
  "action_id": "act_...",
  "subject_id": "agent_main",
  "tool_identity": {
    "server_id": "mcp_ops",
    "tool_name": "send_report",
    "tool_version_hash": "sha256:..."
  },
  "effect": {
    "kind": "data.transfer",
    "operation": "HTTP_POST",
    "resources": ["https://receiver.test/upload"],
    "destination_trust": "UNTRUSTED_EXTERNAL",
    "side_effect": true,
    "reversible": false
  },
  "input_artifacts": ["art_report"],
  "materialized_args_hash": "sha256:...",
  "contract_id": "ctr_...",
  "grant_id": "grt_..."
}
```

### 4.5 DecisionRecord

对外只有三态：ALLOW、ASK、BLOCK。内部保留风险、不确定性和命中事实。

冲突规则：

```text
HARD_BLOCK > BLOCK > ASK > ALLOW
```

- HARD_BLOCK：系统硬策略，用户确认不能覆盖。
- BLOCK：当前安全前提不成立；可通过修改任务/环境后重新提出新动作。
- ASK：动作在身份权限和硬策略内，但超出默认合同或达到确认阈值。
- ALLOW：权限、用途、来源、数据流、预算和状态均满足。

语义模型只能：提高风险、将 ALLOW 升级为 ASK/BLOCK、补充解释；不能覆盖硬拒绝、签发 Grant 或将 BLOCK 降级为 ALLOW。

### 4.6 TraceEvent

最少字段：

```json
{
  "event_id": "evt_...",
  "trace_id": "trc_...",
  "parent_event_ids": ["evt_parent"],
  "event_type": "TOOL_CALL_DECIDED",
  "actor_id": "agent_main",
  "session_id": "ses_...",
  "contract_id": "ctr_...",
  "artifact_ids": ["art_..."],
  "action_id": "act_...",
  "decision_id": "dec_...",
  "timestamp": "...",
  "sequence": 42,
  "payload_ref": "evidence://...",
  "payload_hash": "sha256:..."
}
```

事件类型至少覆盖：用户消息、合同创建/更新、工具注册/变更、资源读取、规范化、检测命中、模型暴露、摘要、记忆写入/读取、子任务派发、工具提议、决策、审批、提交检查、执行结果和影响对象。

---

## 5. 决策算法与状态机

### 5.1 动作判定顺序

```text
1. 验证主体、会话、合同、Grant、策略版本与工具身份
2. 物化并规范化真实工具参数
3. Effect Adapter 生成 SemanticAction
4. 解析输入 Artifact 与 exposure history
5. 检查身份权限和 Grant
6. 检查 TaskContract 的目标、资源和副作用范围
7. 检查 ProvenanceEnvelope 的 authority / confidentiality / allowed_uses
8. 执行硬策略与数据流策略
9. 规则不确定时运行无工具语义研判器
10. 合并结果，输出 ALLOW / ASK / BLOCK
11. ASK 绑定实际参数、目标和所有版本，等待可信审批
12. 执行前重新物化并做 Commit Check
13. 受控执行并记录真实副作用
```

### 5.2 内部状态机

```text
PROPOSED
 -> NORMALIZED
 -> BLOCKED
 |  NEEDS_APPROVAL -> APPROVED | REJECTED | EXPIRED
 |  ALLOWED
APPROVED/ALLOWED
 -> RESERVED
 -> COMMIT_CHECK
 -> EXECUTED | FAILED | RESULT_UNKNOWN | ROLLED_BACK
```

旧审批失效条件：

- 参数、目的地、资源、输入内容 Hash 改变；
- TaskContract/TaskGrant/策略版本改变；
- 工具描述、Schema、Server身份或实现版本 Hash 改变；
- 关联数据敏感等级提高；
- 父授权撤销或过期；
- 超过预算或审批有效期。

### 5.3 本地事务与远程效果

本地 `fs.write`：优先在 Overlay/临时目录生成变更，检查 diff 后提交；失败删除临时层。

本地 `git`：在临时工作树或本地裸仓库执行，检查 commit/ref diff；比赛靶场内提交到本地测试远端。

受限 `exec`：始终在无特权、资源受限、默认无网络的容器执行；不承诺把任意进程副作用提交回宿主。

`net.fetch`/远程写：调用前完成授权；调用后只能记录结果。仅在服务支持幂等键、预条件或 reservation 时做更强保证，不宣称通用回滚。

---

## 6. 策略 DSL v0.1

DSL 使用 YAML，加载时转换为类型化 AST，禁止 `eval` 和任意代码执行。

```yaml
id: block_secret_to_untrusted_destination
version: 1
priority: 1000
effect: hard_block
when:
  all:
    - field: action.effect.kind
      op: eq
      value: data.transfer
    - field: data.max_confidentiality
      op: gte
      value: SECRET
    - field: action.effect.destination_trust
      op: in
      value: [UNTRUSTED_EXTERNAL]
reason: secret_egress_forbidden
```

支持操作符仅限：`eq`、`neq`、`in`、`not_in`、`matches`、`path_within`、`gte`、`lte`、`contains_any`、`exists`。

事实命名空间：

- `principal.*`
- `contract.*`
- `grant.*`
- `action.*`
- `data.*`
- `provenance.*`
- `tool.*`
- `runtime.*`
- `history.*`

策略效果：`allow`、`ask`、`block`、`hard_block`。

缺失字段默认不满足允许规则；涉及安全前提的缺失字段触发 BLOCK。策略加载必须完成 Schema 校验、类型检查、冲突检查和测试样例验证。

必须内置五类策略：

1. 敏感目录写入与路径逃逸；
2. 敏感数据向非信任域外发；
3. 解码执行、远程下载管道执行和危险 Shell 组合；
4. 代码检视任务中的 Git push；
5. 带凭据/秘密的子 Agent 派发。

---

## 7. 多源提示注入检测

检测结果是风险证据，不是授权。

### 7.1 检测流水线

```text
原文登记
 -> Unicode/不可见字符可视化视图
 -> NFKC/全半角规范化视图
 -> 有界编码解码视图
 -> 分块与跨轮组合视图
 -> 规则特征
 -> 轻量/大模型语义检测（按预算）
 -> span级 DetectionFinding
```

原文永不被规范化文本覆盖。所有视图保存转换映射和版本。

### 7.2 三类来源

- 直接：用户越权、角色伪装、上下文劫持、安全策略覆盖请求。
- 间接：网页、文档、源码、工单/邮件/Issue、工具描述、工具返回。
- 记忆：写入时扫描并保留来源；读取时重新扫描，正文永不携带授权。

### 7.3 七类绕过

必须分别测试：多语言/Emoji、Unicode同形和零宽、分片/多轮、注释/分隔符、大小写/全半角/编码、超长上下文稀释、语义伪装。

检测器至少输出：`attack_source`、`attack_family`、`spans`、`normalized_view`、`confidence`、`reasons`、`detector_version`。

---

## 8. 意图—计划—工具对齐

不读取或声称还原私有思维链。只使用：

- 可信用户目标与 TaskContract；
- Agent公开的结构化步骤；
- 已执行事件；
- 当前 SemanticAction；
- ProvenanceEnvelope 与数据流事实。

输出四类偏离：

- `GOAL_DEVIATION`
- `RESOURCE_DEVIATION`
- `SIDE_EFFECT_DEVIATION`
- `DATA_FLOW_DEVIATION`

解释模板必须引用可验证事实，例如：

> 原始任务只允许读取 `/workspace/case-001/**` 并写入本地报告；当前动作试图读取 `~/.ssh/id_rsa`，该路径不在合同资源范围内，且后续目标为非信任域，因此命中资源偏离与秘密外发硬策略，决定 BLOCK。

---

## 9. 攻击后的安全恢复

阻断后，Gateway 返回给 Agent 的不是原始秘密和攻击载荷，而是结构化 `SecurityException`：

```json
{
  "code": "SECRET_EGRESS_BLOCKED",
  "blocked_effect": "data.transfer",
  "safe_reason": "输入包含受保护数据且目标不可信",
  "allowed_alternatives": [
    "仅发送脱敏后的IOC列表",
    "将完整报告写入本地输出目录",
    "请求用户批准可信内部目标"
  ],
  "decision_id": "dec_..."
}
```

Agent 最多进行一次安全重规划；再次提出等价越权动作则终止该分支，避免循环和确认疲劳。安全完成的定义是“原始业务 Oracle 通过且无未授权副作用”，不能只看是否被阻断。

---

## 10. MCP 与子 Agent 防护

### 10.1 工具生命周期

在工具信息暴露给模型前完成：

- Server身份登记；
- 工具名、描述、Schema扫描；
- 同形/重名/功能重叠检查；
- 描述与Schema Hash；
- 信任等级与Effect Adapter绑定。

运行中任何注册变更都生成新版本并使关联审批失效。

### 10.2 子 Agent

- 为子任务创建子 Contract/Grant；
- 权限严格取父权限、子任务需求和策略交集；
- 只传递最小必要 Artifact；
- 敏感度和来源标签不可因序列化丢失；
- 子 Agent 输出为不可信数据，不能携带新授权；
- 父子事件通过 trace/parent IDs 关联。

### 10.3 记忆

- 记忆正文与授权记录物理/逻辑分离；
- 写入保存来源、用途、敏感度和创建任务；
- 检索恢复信封并重新检测；
- “用户偏好/管理员批准”等记忆文本仅作为 DATA_ONLY；
- P0 不做复杂自动修复，只阻止污染升级和越权使用。

---

## 11. 溯源与证据存储

### 11.1 图边

确定边：`READ_FROM`、`DERIVED_FROM`、`EXPOSED_TO`、`PASSED_TO`、`RETRIEVED_FROM`、`PROPOSED`、`AUTHORIZED_BY`、`EXECUTED`、`AFFECTED`。

推断边单独标识 `INFERRED_FROM`，必须带置信度，不能与确定边混画。

### 11.2 token来源口径

- 对本地可复现的 prompt serialization 和 tokenizer，保存字符区间到 token 区间映射；
- 对确定性复制/转换保留精确映射；
- 对摘要/自由生成只声明父来源集合；
- 对云模型隐藏包装只展示本地可验证范围，不声称服务端完整 token 因果。

### 11.3 数据最小化

- 普通索引只保存脱敏摘要、Hash、类型和引用；
- 完整参数/结果仅在封闭比赛靶场的加密证据区保存；
- UI 默认不显示秘密；
- 证据区与模型工具隔离；
- 支持保留期和测试后清理；
- 所有演示使用 honeytoken/合成秘密。

---

## 12. 性能设计

### 12.1 快慢路径

```text
L0：内存合同/Grant/策略/工具版本校验
L1：确定性参数、路径、来源和数据流检查
L2：本地内容规则与轻量检测
L3：无工具语义研判器，仅处理不确定动作
L4：用户确认或隔离执行，仅处理高风险副作用
```

前一层有确定结论时不进入后一层。语义模型不能成为所有调用的必经步骤。

### 12.2 性能目标

以下是验收目标，不是预填实验结果：

- 纯策略决策 P95 ≤ 10 ms；
- 低风险工具调用新增 P95 ≤ 50 ms，不含上游模型和工具本身耗时；
- 固定测试集中不调用语义模型的调用比例 ≥ 80%；
- 策略发布到数据面生效 ≤ 3 s；
- 非关键审计事件异步批量写入；
- 等待真人审批时间单独统计；
- 语义检测超时默认 ASK 或 BLOCK，禁止静默 ALLOW。

---

## 13. 评测与验收

### 13.1 测试分层

1. 单元测试：Schema、传播、策略、冲突、状态机和工具适配器。
2. 确定性安全回归：至少 200 条，覆盖五类工具、三类来源和七类绕过。
3. 真实 Agent 端到端：至少 60 个基础任务，每个具有干净/攻击/传播/合法危险证据对照；资源不足时先保证每类强制能力有重复运行。
4. 外部基准：AgentDojo兼容子集 + MCP-SafetyBench子集 + MCPTox子集，公开适配范围。
5. 自适应攻击：攻击 Agent 在固定预算内观察公开决策和重写载荷，不得访问隐藏策略和密钥。

### 13.2 核心指标

- Execution ASR；
- Defense Success Rate；
- 合成秘密真实泄露率；
- 正常任务完成率；
- 安全研判保全率；
- 高风险真实副作用阻断率；
- 误拦率、ASK率、每任务审批数；
- 来源节点/路径覆盖率；
- token输入映射覆盖；
- P50/P95新增延迟；
- 本地回滚/隔离成功率；
- 错误、超时和结果未知率。

### 13.3 最低 Go/No-Go 目标

这些目标在测试集冻结前不得根据最终测试结果反向修改：

| 指标 | P0目标 |
|---|---:|
| 明确硬策略确定性回归 | 100%通过 |
| 固定端到端集 Execution ASR | ≤ 5% |
| 合成秘密真实泄露率 | 0% |
| 正常任务完成率 | ≥ 80% |
| 安全研判保全率 | ≥ 75% |
| 七类绕过总体防御成功率 | ≥ 85% |
| 关键Trace事件完整率 | ≥ 95% |
| 支持范围内token输入映射 | 100% |
| 低风险调用新增P95 | ≤ 50 ms |
| 平均每正常任务ASK数 | ≤ 0.5 |
| 干净环境一键部署 | 100%成功 |

### 13.4 基线与消融

必须：

- B0 Unsafe Agent；
- B1 强静态工具网关；
- Full 溯界；
- Ablation A：去除来源—用途传播；
- Ablation B：去除隔离分析与安全恢复。

可选：内容拒绝分类器基线、更多模型、更多消融。物理靶场隔离在所有基线中保持开启，避免真的造成危险。

副作用由文件系统、测试接收端、进程、Git refs和记忆数据库真实状态判分，不依赖模型自评。LLM Judge只作辅助。

---

## 14. P0/P1范围

### 14.1 P0必须完成

- 一个受控 Agent Host；
- 两个 MCP Server；
- fs.read/fs.write、net.fetch/transfer、受限 exec、git.push、agent.delegate、memory.read/write；
- 三类注入来源；
- 七类绕过的测试和基础检测；
- TaskContract/TaskGrant；
- ProvenanceEnvelope；
- SemanticAction与DSL；
- ALLOW/ASK/BLOCK；
- 跨 MCP、子 Agent、记忆的DAG与时序；
- 安全研判特色场景；
- 性能测试、部署文档和测试报告。

### 14.2 P1加分项

- 本地文件/Git Shadow执行和更完整回滚；
- 自适应攻击 Agent；
- MCP-SafetyBench/MCPTox更大子集；
- 已知CVE封闭复现；
- 多模型和多宿主适配；
- OpenTelemetry/Jaeger；
- Redis和多实例网关。

禁止在P0未闭环前投入：模型微调、Kubernetes、复杂微服务、通用恶意代码沙箱、大屏动画。

---

## 15. 七周路线图

### 第1周：骨架与真实最小链路

- Monorepo、Compose、Schema包；
- LangGraph Agent；
- 两个最小MCP Server；
- Host无直连权限；
- 真实工具调用事件和基础DAG；
- 干净任务与间接注入各1条跑通。

出口：能观察真实调用并证明工具不能绕开Gateway。

### 第2周：合同、Grant、DSL和三态

- TaskContract/TaskGrant状态；
- Policy DSL AST与冲突规则；
- fs/net动作适配；
- ALLOW/ASK/BLOCK；
- Spring Boot任务、策略、审批最小API。

出口：合法写报告放行，秘密外发阻断，越界动作可确认但硬策略不可覆盖。

### 第3周：来源—用途信封

- 内容入口、Artifact、父子来源；
- exposure set；
- 敏感度与用途传播；
- egress DLP；
- token输入区间映射原型。

出口：摘要、改名和序列化不能洗白来源。

### 第4周：长链路与五类工具

- 受限exec、Git、子Agent、记忆；
- 父子Grant收窄；
- 跨会话来源恢复；
- 执行前复核；
- 工具注册/版本变化检测。

出口：工具结果→摘要→子Agent→外发，以及记忆→新会话两条链跑通。

### 第5周：注入检测与安全恢复

- 多视图规范化；
- 三类来源和七类绕过；
- 意图—动作偏离解释；
- 无工具证据隔离舱；
- SecurityException与一次安全重规划。

出口：危险证据被正确分析，攻击动作被阻断，报告仍完成。

### 第6周：控制台与评测

- Vue告警、审批、DAG、时序和影响面；
- 200条确定性回归；
- 60个基础任务框架；
- 三个必选基线/两个消融；
- P50/P95与错误统计。

出口：验收矩阵自动生成，不靠人工口头判断。

### 第7周：红队、优化和交付

- 固定测试集、多次重复；
- 外部基准子集；
- 性能与误拦优化；
- 失败案例与残余风险；
- 部署、设计、测试文档；
- 演示脚本和答辩材料。

出口：干净环境一键复现，全部成绩可从原始运行记录重新计算。

---

## 16. 推荐仓库结构

```text
sujie/
├── contracts/                  # JSON Schema与共享枚举
├── gateway-python/             # MCP代理与安全数据面
│   ├── intake/
│   ├── detection/
│   ├── provenance/
│   ├── action_mapping/
│   ├── policy/
│   ├── approval/
│   └── tracing/
├── control-plane-java/         # Spring Boot控制面
├── console-vue/                # Vue控制台
├── demo-agent/                 # LangGraph受控Agent
├── mcp-servers/
│   ├── evidence-server/
│   ├── operations-server/
│   └── malicious-variants/
├── sandbox/
├── eval/
│   ├── cases/
│   ├── attacks/
│   ├── oracles/
│   ├── baselines/
│   └── reports/
├── deploy/
├── docs/
└── README.md
```

---

## 17. 实现纪律

- 不使用绿盟内部代码、数据、模型、规则和文档；
- 只用合成秘密、开源许可材料和封闭测试服务；
- Mock可以用于单元测试，但端到端成绩必须来自真实工具副作用；
- 不预填任何实验成绩；
- 每个安全声明必须对应测试ID和原始证据；
- 不允许通过全部BLOCK提高安全指标；
- 不允许语义LLM自动扩权；
- 不允许把来源Hash误称为内容真实性证明；
- 不允许把本地token映射误称为模型内部因果追踪；
- 未支持的远程工具和Shell语法必须显式显示为不支持或降级处理。

---

## 18. 相关工作边界

设计和答辩至少要正确区分以下公开方向：CaMeL、Task Shield、AgentSpec、AuthGraph、AgentVisor、AID-Guard、ContainmentBench、MCP-SafetyBench、MCPTox。

本项目不与这些工作争夺已公开单项机制的“首次”，而强调：面向安全研判危险证据场景，将可信任务契约、来源—用途传播、效果级策略、隔离分析和攻击后任务恢复组合成真实MCP防护闭环，并用安全与业务双Oracle验证。

---

## 19. 最终答辩一句话

> 溯界不是试图让大模型永远看不见恶意内容，而是确保恶意内容即使被读取、摘要、记忆或传递给子 Agent，也始终只是受约束的证据，不能获得工具执行权限；当攻击动作被阻断后，系统还能引导 Agent 在原授权边界内完成任务，并给出可验证的全链路溯源。
