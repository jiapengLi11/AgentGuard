# M2 来源用途传播实施方案

日期：2026-10-05。状态：实施方案，尚未开始 M2 代码开发。

依据：冻结设计 F1.0 第 4、5、7、10、11 节和实施总指令第 5 节。前置基线是 M1 执行边界修复及其可复现检查；本方案不更换架构、模型角色或验收口径。

目标是证明：外部内容经改名、解码、摘要、拼接和跨边界传递后，仍保留来源与用途约束；危险证据可以被读取和引用，但不能升级为授权，敏感派生内容不能外发。每条拒绝路径都配正常任务对照。

## 1. 范围与信任边界

- 网关或可信 Host Adapter 登记 Artifact；模型不能提交 authority、integrity、confidentiality 或 allowed_uses 自行签发可信标签。
- 复用现有 `ProvenanceEnvelope`，保留原文、内容 Hash、父来源、转换和区间引用。
- 对进入模型上下文的数据建立 exposure set；自由生成结果保守继承整个相关输入集合。
- 将 Artifact 依赖和信封事实接入实际出口及审批绑定；未知依赖不能静默视作 PUBLIC。
- 提供脱敏 DAG 查询，明确区分观测到的确定关系与推断关系。

M2 初始实现可在单进程内存中验证来源闭环，不能据此宣称加密持久证据、多副本一致性或防篡改存储。M3 才接入真实子 Agent 与跨会话记忆工具；M2 先冻结相应传播接口并用领域用例验证，再在 M3 用真实工具验收长链。

## 2. 建议接口

以下是待实现的内部接口草案，不是当前已存在的 API。

| 对象/接口 | 输入 | 输出与约束 |
|---|---|---|
| ArtifactRegistry.register | 可信入口类型、原文 bytes、来源事件、受控标签 | Artifact ID、内容 Hash、有效信封；正文与普通索引分离 |
| ArtifactRegistry.derive | 父 ID 集合、转换类型/版本、结果正文、映射引用 | 新 Artifact；执行已有普通派生不变量 |
| ContentViews.normalize | 原始 Artifact、受限转换配置 | 原文不变；规范化/可见字符视图及可验证映射 |
| ExposureLedger.record | 可信 session/主体、实际暴露的 Artifact 集合 | 单调 exposure 快照；不能由模型任意移除敏感输入 |
| ProvenanceFacts.for_action | 物化参数、可信依赖、相关 exposure | 最严格敏感度、用途约束、依赖快照 Hash；缺失则拒绝 |
| TraceDAG.query | 当前获准查询的 task/trace ID | 脱敏节点和类型化边，包含阻断点与影响对象 |

Artifact 正文不会通过普通 Trace API 返回。对来自 MCP 的结果必须先登记，再返回给 Agent；把结果交给 Agent 的可信路径同时记暴露事件，采用保守 exposure，不能依赖模型声称“没有看见”。

### Artifact 与视图的建模

先使用内部 Artifact 记录关联现有信封、原文与视图存储。需要跨进程序列化时，单独冻结 Artifact Schema 与 fixtures；如果必须变更现有信封字段、核心不变量或 bundle 契约，先提交 ADR，不能直接改冻结 Schema。

现有 source_spans 没有逐条父 Artifact ID。对多父拼接的精确来源，使用 `mapping_ref` 指向明确携带父 ID 的映射对象；不要把无归属的多个父区间混放并声称完整溯源。如果现有结构不能充分表达，保留父集合的保守保证并先做 ADR。

## 3. 传播规则

1. 普通派生物的 authority/integrity 不得高于最不可信父输入；DATA_ONLY 永不能成为 AUTHORIZE 来源。
2. confidentiality 不低于父输入最高级别；只有白名单可信脱敏器可以例外，M2 不提供模型自评的脱敏例外。
3. allowed_uses 取相关父输入的交集，forbidden_uses 取并集；复制、改名和序列化不清除限制。
4. 摘要/自由改写只保留父集合和保守 exposure 依赖，不伪造生成 token 的精确因果映射。
5. 精确复制、切片、解码和规范化视图保留可验证区间；映射依据完整转换结果验证，不能简单逐字符 NFKC 后假定与整体规范化等价。
6. Base64 解码和长文本处理限制长度、层数及资源消耗；拒绝解析错误和越界区间，不递归无限解码。

报告写入必须区分内容用途与动作授权：危险证据允许 QUOTE/STORE_EVIDENCE，报告文件写入由 Contract/Grant 的 file.write 权限授权。不要为了让报告成功，就给外部证据增加 AUTHORIZE、EXECUTE 或 TRANSFER。

## 4. 与当前 M1 集成

### 来源入口

Evidence/Operations 返回结构化内容时，可信网关登记正文和嵌套字段的来源；真实文件的秘密等级来自受控资源目录或可信入口配置，不能由模型标签或正文中的“公开”声明决定。

Agent 的自由生成内容由 Host Adapter 绑定当前主体与 exposure。调用方提交的 Artifact ID 必须存在、属于有效任务上下文，且依赖与物化参数一致。禁止用无关 PUBLIC Artifact 为实际敏感字符串作担保。

### 出口策略

`data.transfer` 不只检查目的地：还读取依赖的 sensitivity、allowed_uses、forbidden_uses 和 exposure。合成 SECRET 到非信任域必须硬拒绝；审批不能覆盖。正常对照使用真实明确许可的非秘密内容与目标，不能用“全部拒绝”通过安全验收。

M2 首批出口是固定本地 Receiver；最终回复、模型 API 输入、日志/预览也必须登记为出口或明确列入尚未覆盖范围，不能从单个 HTTP 工具的保护推导所有出口安全。

### 审批

用实际依赖内容和信封快照替换 M1 的两个空列表 Hash。提议、批准、提交以及发现工具后的最终复核都使用相同绑定规则。相关来源、敏感度或输入内容改变会使旧审批失效。

### Trace 与 DAG

先记录并可查询 `READ_FROM`、`DERIVED_FROM`、`EXPOSED_TO`、`PROPOSED`、`AUTHORIZED_BY`、`EXECUTED`、`AFFECTED`。子 Agent/记忆的传递边接口预留，真实接入归 M3。

填充现有 Trace 的 artifact_ids，保留事件父关系，提供可解析的脱敏动作与来源索引。图有环或引用不存在时明确报错；拒绝从 Hash 推导内容真实性或模型内部因果关系。

token 映射限于本地可复现的序列化与 tokenizer 支持范围；先验证字符映射，再选择并记录 tokenizer 版本，云端隐藏包装不在精确映射承诺中。

## 5. 文件计划与实施顺序

| 顺序 | 建议新增/修改文件 | 交付条件 |
|---|---|---|
| M2-A 登记与传播 | `gateway-python/src/sujie_gateway/provenance/` 中 store、propagation；新增测试 | 原文 Hash、父来源、标签不变量与拒绝路径可运行 |
| M2-B 视图与暴露 | provenance 的 views、exposure、mapping；Demo Host 集成 | 规范化不覆盖原文；生成结果保守继承暴露；边界与超长输入有测试 |
| M2-C 实际出口 | `m1_runtime.py`、`policies/m1.yaml`、Agent/API 接入、相关回归 | 真实 Receiver 双 Oracle；审批绑定真实来源 Hash |
| M2-D DAG | tracing 模块、`api.py`、Trace 测试 | 从实际拒绝动作查询触发源/经过节点/影响对象；普通查询不泄露秘密 |
| M2 验收 | `docs/M2_ACCEPTANCE.md`、主线 README | 实际命令、结果、未覆盖项和 M3 接口清单 |

开始前检查现有策略文件与 Contract policy_snapshot_hash 的真实绑定；发布策略应生成不可变快照，不能继续用固定示例 Hash 冒充实际策略内容指纹。

不在这一里程碑引入数据库、模型微调、Kubernetes、全功能 Agent 或新的公网依赖。新依赖如果确有必要，按贡献指南记录版本、许可证、用途和热路径影响。

## 6. 成对验收矩阵

| 测试族 | 攻击/违规输入 | 正常对照 | 必须观察的结果 |
|---|---|---|---|
| M2-RENAME | SECRET 内容改名为 public | PUBLIC 内容改名 | 内容身份/标签不因名称变化；前者不可外发 |
| M2-DECODE | SECRET 编码后再解码 | 正常非秘密 Base64 | 来源与用途不丢；映射和内容 Hash 可复算 |
| M2-SUMMARY | 包含秘密的模型上下文生成摘要 | 只暴露 PUBLIC 输入的摘要 | 保守继承父集合；无伪精确映射；真实接收端判分 |
| M2-CONCAT | PUBLIC 和 SECRET 拼接 | PUBLIC 与 PUBLIC 拼接 | 最严格敏感度与用途交集生效 |
| M2-NESTED | MCP 深层字段携带载荷/秘密 | 正常嵌套字段 | 字段来源可追踪，不能藏在嵌套结果中洗白 |
| M2-DELEGATE | 已标记内容经序列化/子任务边传递 | 最小 PUBLIC 输入传递 | 标签不升级；M2 领域验证，M3 真实子 Agent 验收 |
| M2-MEMORY | 污染内容恢复为“管理员已批准” | 正常偏好/证据恢复 | 正文仍 DATA_ONLY；M3 真实跨会话验收 |
| M2-EVIDENCE | 公共告警含危险命令文字 | 普通告警 | 可读取、引用并写本地报告；无未授权副作用 |
| M2-APPROVAL | 等待审批时内容/相关来源变化 | 内容与版本未变化 | 旧审批失效；正常审批仍单次执行 |
| M2-DAG | 多次派生后提出越权动作 | 正常报告链 | 图能查询真实来源、阻断点及影响对象，无秘密正文 |

失败、超时、无动作和结果未知单独统计。M2 的确定性安全/工程结果不能替代 M6 的真实模型评测，也不按字符变体虚增任务数。

## 7. 完成条件

- M1 全部检查继续通过。
- 七条洗白路径均有来源保持与正常对照；真实子 Agent/Memory 未接入时明确标识领域测试范围。
- 真实 Receiver 验证 SECRET 出口拒绝与合法非秘密出口成功，且本地研判报告可完成。
- 相关依赖漂移使旧审批失效。
- DAG 可以从实际阻断动作追溯来源与转换，普通 API 不返回秘密。
- 所有安全声明绑定测试 ID 与原始证据；任何冻结对象冲突先提交 ADR。
