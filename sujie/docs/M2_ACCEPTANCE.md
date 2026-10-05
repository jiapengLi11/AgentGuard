# M2 首轮实现与接力验收

日期：2026-10-05。工作分支：`feat/m2-provenance-egress`。本轮实现 M2 的单进程来源闭环，基于 PR #4 的交付雏形；不执行合并。架构基线仍为 F1.0，九类 Schema、三态语义、数据面/控制面和 Agent 权限保持原定义。

## 已实现

- **可信登记**：原文 UTF-8 字节、真实 SHA-256、来源事件、不可变 `ProvenanceEnvelope`；模型不能提交标签或用途声明作为授权。
- **普通传播**：复制/改名、切片、Base64、拼接、NFKC/可见字符视图、摘要/自由改写和嵌套 JSON 字段提取；父来源、DATA_ONLY/UNTRUSTED、最高敏感度、用途交集与禁止用途并集保持。
- **实际暴露**：受控 MCP 返回在交给 Agent 之前登记；可信 Host 解码视图后再次记录暴露；自由输出保守继承当前主体全部已暴露输入。
- **效果出口**：真实内容参数由网关绑定为 Artifact；检查 Contract/Grant、用途、来源和当前暴露；M2 YAML 使用数值等级拒绝 CONFIDENTIAL/SECRET 到固定非信任 Receiver，普通内容保留 ASK 单次提交。
- **真实审批摘要**：实际内容与相关有效信封/暴露快照替代 M1 的空列表占位；提议、批准、提交、异步发现之后均复核。可信分类收紧、用途收紧或新增暴露使旧审批失效。
- **文件读回**：成功写入的文件关联其输入 Artifact；随后读回继承原来源和更严格分类，不能按新文件名清除约束。Evidence 在解析前拒绝静态 symlink/junction，避免来源目录分类被链接绕过。
- **脱敏 DAG**：查询 Artifact、主体、动作、当时的 Contract/Grant 引用与资源摘要；覆盖 DERIVED_FROM、EXPOSED_TO、READ_FROM、PROPOSED、AUTHORIZED_BY、EXECUTED/AFFECTED；生成依赖明确标为保守关系。
- **真实 Agent 演示**：LangGraph 在 ASK 处暂停，由可信脚本完成网关审批和提交后恢复；SECRET 摘要外发被 BLOCK 后，Agent 继续写成本地报告。两种任务生成相同摘要，以验证结果来自来源约束。

SUBAGENT_PASS / MEMORY_RESTORE 本轮是同一注册表内的领域传递/恢复规则，并经过真实 Receiver 出口检查；尚未实现真实子 Agent、Memory 服务或跨会话持久恢复。这些真实工具属于 M3，不能把本轮测试表述成完整长链工具验收。

## 运行与演示

在 `sujie/` 下使用已安装锁定依赖的 Python 3.12 环境：

```bash
.venv/bin/python dev.py check
.venv/bin/python dev.py provenance-demo --output ../artifacts/m2-delivery
```

Windows 使用 `.\.venv\Scripts\python.exe`。不需要模型 API Key；这是确定性模型的工程验证，不是真实 LLM 评测。输出目录已有时拒绝覆盖。

输出 `m2-run.json` 包含真实 Oracle 汇总、源码版本与运行文件哈希、脱敏 DAG 和冻结 TraceEvent 元数据，不保存原告警、报告、Receiver 请求体或 canary。它是回放证据格式 `sujie-m2-demo/1`，不是新的业务契约或审批凭证。M1 的 `dev.py demo` / `deliver` 继续使用原有语义。

两个任务使用相同权限和目的地：

| 任务输入的可信分类 | 实际模型输入 | 外发摘要 | 结果 |
|---|---|---|---|
| PUBLIC | 真实文件→MCP→Base64 解码视图 | 固定中性摘要 | ASK；批准前不发送，批准后 Receiver 1 次；报告完成 |
| SECRET | 同上，源包含合成 canary | 与 PUBLIC 完全相同 | 硬 BLOCK；Receiver 0 次；随后报告完成且无 canary |

Receiver 另在独立临时场景发送 canary 做正向校准；校准不计入 Agent 泄露结果。`same_summary` 检查两个摘要哈希相等，不能只靠秘密字符串扫描解释结果。

## 可选 API 集成

现有 API 的默认模式仍为 M1。可信部署配置 `SUJIE_PROVENANCE_MODE=1` 才启用 M2；不增加端口或审批接口。已存在的 `/v1/calls` 返回正文之前先登记来源，并额外返回 Artifact ID 与字段指针。

- `GET /v1/provenance`：当前进程内唯一活动任务/主体的脱敏图；M1 模式返回 404；没有任意任务选择器或正文接口。
- `SUJIE_RESOURCE_LABELS`：可信启动配置的 JSON 对象，示例 `{"operations:case-001/input.txt":"SECRET","evidence:clean":"PUBLIC"}`。类别只能是 PUBLIC/INTERNAL/CONFIDENTIAL/SECRET，Agent 请求不能修改它。
- `SUJIE_SYNTHETIC_FIXTURE_MODE=1` 时两个已知合成 Evidence 样例有 PUBLIC 配置；其他未分类读源默认拒绝。成功写入的文件可以通过已登记父来源恢复分类。

该 API 沿用 M1 的内部进程/网络边界，不是已认证的多租户控制面；M5 还需提供身份、任务访问控制和审批服务。部署者不能仅凭这个查询端点宣称生产授权已完成。

## 来源与映射口径

- 字符区间按 Python Unicode code point 计，不是 UTF-16、UTF-8 byte 或模型 token offset。
- COPY/SLICE 有明确区间；CONCAT 用内部 `mapping_ref` 分别携带父 ID，并显式记录固定 LF 分隔符，不把多父区间混入无父归属的字段。
- NFKC 对整串规范化后计算映射，并验证分段转换；无法可靠分段时保守覆盖整个视图。不会逐字符规范化后假装与整串等价。
- Base64 采用整值映射；JSON_FIELD 采用经过实际解析验证的字段路径及保守包围区间，不声称逐字符精确来源。
- SUMMARY/MODEL_REWRITE 只保留父集合和保守暴露依赖，`source_spans=[]`、`mapping_ref=null`，不伪造生成 token 因果。
- 原内容与保存的信封快照不可变；可信 `tighten` 只收紧分类/TRANSFER 用途，现有后代在决策时继承收紧，审批快照随之变化。模型没有此接口，也没有脱敏降级例外。

内容上限 256 KiB/Artifact，累计内容 4 MiB，累计映射 4 MiB，最多 1024 Artifact、256 父来源/暴露项、32 层来源；Base64 血缘最多 4 次 DECODE，嵌套 JSON 最多 12 层及 128 个字符串叶。上限只覆盖登记/视图处理，不是 SDK 传输层或整个服务的通用 DoS 保证。

## 验收矩阵

| 测试 ID | 验证重点 |
|---|---|
| M2-STORE-001 | 七条路径 PUBLIC/SECRET 成对领域传播，真实字节哈希和普通派生不变量 |
| M2-STORE-002 至 004 | 外来/未知 ID、缺失暴露、单调收紧、用途交集、快照不可变、自签标签拒绝 |
| M2-STORE-005 至 009 | Unicode 组合/Hangul/空输入、可见字符/切片、错误与深层解码、嵌套/容量/映射上限、脱敏图 |
| M2-E2E-001 | 七条路径 PUBLIC/SECRET 成对真实 MCP + Receiver；子 Agent/Memory 只为领域适配器 |
| M2-E2E-002 | 真实 LangGraph 暂停/恢复；先 BLOCK 外发、后完成报告 |
| M2-E2E-003/004 | 批准前、提交前、异步工具发现后，来源/暴露/用途漂移导致审批失效，无 HTTP POST |
| M2-E2E-005/006 | 未暴露隔离输入不误伤；报告读回仍保留敏感来源 |
| M2-E2E-007/008 | 缺失、自签、未知源、错策略、跨主体上下文与用途拒绝；危险公共证据仍可引用 |
| M2-E2E-009 至 011 | 数值敏感等级、Evidence 链接拒绝、历史授权图保留当时 Grant ID |
| M2-API-001 | M1/M2 两种模式、冻结事件校验、脱敏查询、模型标签和审批入口拒绝 |
| M2-DEMO-001 | 真实 CLI、成对 Agent、Oracle、无秘密正文的证据输出与图引用有效 |

完整检查继续包含 M1 授权有效期、预算、路径、审批、Schema 与交付包回归。测试数量包含参数化和领域检查，不能算作比赛攻击任务数、200 条安全攻击验收或真实模型防御率。

## 本轮验证记录

macOS / Python 3.12.15，本地于 2026-10-05 验证：

- `dev.py check`：Ruff 检查与格式检查通过，281 项测试通过，82.19 秒；一个已存在的 Starlette/AnyIO 弃用提示。
- `dev.py provenance-demo`：`public`、`secret`、`oracle`、`same_summary` 四项检查均通过；PUBLIC 批准后 Receiver 1 次，SECRET 为 0 次，两种任务均完成报告。
- 两种摘要的真实 SHA-256 相同：`d8f5d4f0acd19bd554057db7ed497d7ae7688fde659d444f0d082bbb3e6887d0`。
- 九类冻结 Schema、锁定依赖、Compose 和容器网络配置均未修改。本机未运行 Docker；Ubuntu/Windows 结果以本分支 GitHub Actions 为准。

关联任务：[Issue #5](https://github.com/jiapengLi11/AgentGuard/issues/5)。演示证据在提交后重新生成，以 `source.revision` 和 `working_tree_dirty=false` 标识实际验收的源码。

## 接力边界与未覆盖项

1. Registry、exposure、文件血缘和审批均为当前 Gateway 的单进程内存状态，重启/多副本不能恢复，也不能以同一个公开 Artifact ID 跨任务自由取用。
2. 来源覆盖限定为受控 MCP、可信视图适配器和本轮固定模型上下文。真实模型接入必须让可信 Host 捕获全部实际输入；未登记的浏览器、RAG、用户额外上下文、模型 API 输入和回复/日志出口不在本轮完整性声明内。
3. 分类来自可信资源目录与单调收紧，不是完整的敏感内容识别器；给源配置错误的 PUBLIC 标签不能靠来源传播自行纠正。
4. M2 严格绑定实际加载的 YAML 文本 Hash；M1 的 Schema fixture 仍保留历史示例 Hash，不能把所有 fixture 当作已发布策略。热更新、签名发布属于后续控制面。
5. `payload_ref` 仍是 M1 进程内引用，未提供普通正文查询或持久证据库。静态链接检查不提供 TOCTOU 保证。真实 exec/Git/delegate/memory、M4 检测/恢复、M5 Java/Vue 和 M6 模型指标尚未实现。
6. 本分支依赖交付 PR #4、间接依赖修复 #2；只提交自己的增量，由队友决定验收与合并顺序，不操作队友分支。
