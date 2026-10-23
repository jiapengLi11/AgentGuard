# 溯界（Sujie / AgentGuard）

> 结项前根 README 的历史快照，仅供追溯。下文相对链接按原仓库根目录解释，旧进度不代表当前状态；请以[当前 README](../README.md)和[结项说明](PROJECT_CLOSEOUT_2026-10-23.md)为准。

## 赛题5 五项能力完成状态（2026-10-19 核对）

> 核对方法：逐项对照[赛题原文快照](competition/research/2026-10-14/topic5-official.json)与本分支源码/测试，以[主线能力审计](competition/docs/MAIN_CAPABILITY_AUDIT_2026-10-19.md)（基线 `fb6e6e4`）为起点，补入其后的 PR #20（结构化返回来源）、PR #21（检测器 `detection_v2`）与本次敏感写入硬策略。
> 状态口径：**已完成**＝代码+自动化测试覆盖赛题列明范围；**部分完成**＝有真实实现与测试，但赛题列明子项仍有缺口；**未完成**＝无实现。检测指标仅为规则初筛的离线评测，**不是 Agent ASR**。

### 总览

| 能力 | 状态 | 关键证据 | 主要缺口 |
|---|---|---|---|
| 1 多源注入识别 | 部分完成 | [`tool_result.py`](sujie/gateway-python/src/sujie_gateway/tool_result.py)、[`detection_v2.py`](sujie/gateway-python/src/sujie_gateway/detection_v2.py)、[`test_tool_result_sources.py`](sujie/tests/test_tool_result_sources.py)、[`test_operator_memory_cycle.py`](sujie/tests/test_operator_memory_cycle.py) | 无真实 PDF/DOCX/源码提取适配；无同会话追加多轮 API；记忆仅固定 key，无检索式召回 |
| 2 意图—计划—工具对齐 | 部分完成 | [`alignment.py`](sujie/gateway-python/src/sujie_gateway/alignment.py)、[`sequence_alignment.py`](sujie/gateway-python/src/sujie_gateway/sequence_alignment.py)、[`test_alignment.py`](sujie/gateway-python/tests/test_alignment.py)、[`test_sequence_alignment.py`](sujie/tests/test_sequence_alignment.py) | 解释主要在 BLOCK 后生成，缺执行前独立偏离评估；跨轮组合越权仅覆盖“读凭据→外发” |
| 3 工具策略 DSL 与三态 | 部分完成（五类规则均有实现） | [`dsl.py`](sujie/gateway-python/src/sujie_gateway/dsl.py)、[`policies/m1.yaml`](sujie/gateway-python/policies/m1.yaml)、[`sensitive_targets.py`](sujie/gateway-python/src/sujie_gateway/sensitive_targets.py)、下表五个测试 | 风险等级由决策反推（`ALLOW→LOW`，否则 `HIGH`），不是独立运行时风险；DSL 获得的上下文事实少 |
| 4 跨 MCP 与子 Agent 溯源 | 部分完成（主体已补齐） | [`provenance_graph.py`](sujie/gateway-python/src/sujie_gateway/provenance_graph.py)、[`provenance_export.py`](sujie/gateway-python/src/sujie_gateway/provenance_export.py)、[`test_provenance_graph.py`](sujie/tests/test_provenance_graph.py)、[演示产物](sujie/docs/provenance-demo/README.md)、控制台“攻击链路溯源”页 | token 区间用确定性简单分词器、编码载荷仅到 Artifact 级；控制台未接 Recorder（参数为规范化效果+哈希）；演示 Agent 为脚本驱动 |
| 5 对抗鲁棒性（七类绕过） | 部分完成（七类均有规则与测试） | [`detection_v2.py`](sujie/gateway-python/src/sujie_gateway/detection_v2.py)、[`zh_rules.py`](sujie/gateway-python/src/sujie_gateway/zh_rules.py)、[`test_seven_bypass_matrix.py`](sujie/tests/test_seven_bypass_matrix.py)、[`run_public_injection.py`](sujie/eval/run_public_injection.py) | 公开数据集 held-out 召回仅 30.6%；角色扮演/语义伪装依赖规则，尚无统一语义检测编排；真实多轮拆分未闭环 |

### 能力1 多源注入识别

| 子项 | 状态 | 证据 | 缺口 |
|---|---|---|---|
| 直接注入（用户输入） | 已完成 | `M1Gateway.register_user_input()`；[`test_bypass_runtime.py`](sujie/tests/test_bypass_runtime.py) DIRECT 参数化 | 仅建任务时一次输入 |
| 间接：URL/网页 | 已完成 | [`network_policy.py`](sujie/gateway-python/src/sujie_gateway/network_policy.py)；`test_real_web_read_registers_origin_and_same_origin_redirect`（[`test_network_gateway.py`](sujie/tests/test_network_gateway.py)） | — |
| 间接：文档 / 源码 | 部分完成 | 附件审计、证据读取等合成业务（[M21](sujie/docs/M21_FOUR_BUSINESS_WORKFLOWS.md)） | 无真实 PDF/DOCX/IDE 源码提取器 |
| 间接：工单/邮件/Issue | 部分完成 | issue-triage、event-timeline 合成业务；[`agent_safety_bench_zh`](sujie/eval/public_injection_sources.py) 等公开样本离线评测 | 无真实邮件/Issue 服务适配 |
| 间接：MCP 返回字段 | 已完成 | PR #20：嵌套/数组/额外字段及字段名均登记并扫描；`test_all_result_text_gets_registered_detected_and_bound_to_model_input` | — |
| 间接：MCP 工具描述 | 已完成 | `StdioMCPProxy` 扫描工具元数据并绑定版本；[`test_tool_registration.py`](sujie/gateway-python/tests/test_tool_registration.py)；公开集 mcp_tool_poisoning held-out 召回 75% | — |
| 记忆污染 | 部分完成 | [`memory_detection.py`](sujie/gateway-python/src/sujie_gateway/memory_detection.py)、跨会话 Memory（[M18](sujie/docs/M18_CROSS_SESSION_MEMORY.md)）、[`test_operator_memory_cycle.py`](sujie/tests/test_operator_memory_cycle.py) | 无检索/chunk 召回接口 |

### 能力2 意图—计划—工具语义对齐

| 子项 | 状态 | 证据 | 缺口 |
|---|---|---|---|
| 可信任务意图（TaskContract） | 已完成 | 九类契约 [`contracts/schemas`](sujie/contracts/schemas) | 目标主要来自固定 profile |
| 偏离判定与可解释结论 | 部分完成 | `explain_alignment()` 输出 GOAL/RESOURCE/SIDE_EFFECT/DATA_FLOW 四维解释 | 仅在 BLOCK 后调用，非执行前独立评估 |
| 多步/跨轮组合偏离 | 部分完成 | `sequence_alignment.py` 记录 credential.read→transfer，保留 UNKNOWN | 缺“编码后外发、分片累计、读后委派、子 Agent 中转”等组合状态机 |

### 能力3 工具策略 DSL 与三态决策

| 赛题列明规则 | 状态 | 证据 |
|---|---|---|
| fs.write 敏感路径 | 已完成（本次补强） | [`sensitive_targets.py`](sujie/gateway-python/src/sujie_gateway/sensitive_targets.py)：`.ssh`/`authorized_keys`/`.git/hooks`/CI 工作流/`.env`/shell 启动文件/私钥/`.vscode` 等在**放宽的可信 Grant 下仍硬阻断**；[`test_sensitive_write_targets.py`](sujie/tests/test_sensitive_write_targets.py)（真实 stdio MCP，文件确认未生成，含正常对照） |
| net.fetch 外发会话内已读秘密 | 已完成 | `test_read_secret_then_query_header_body_exfil_is_blocked_before_http`（[`test_network_gateway.py`](sujie/tests/test_network_gateway.py)） |
| exec base64 / curl\|sh | 已完成 | [`execution_policy.py`](sujie/gateway-python/src/sujie_gateway/execution_policy.py) 只允许注册程序与确切 argv；[`test_execution_gateway.py`](sujie/tests/test_execution_gateway.py) 含 base64 解码执行与 curl 用例 |
| 代码检视期间 git.push | 已完成 | `test_review_blocks_push_and_explicit_publication_asks_then_exact_commit_once`（[`test_git_delivery_gateway.py`](sujie/tests/test_git_delivery_gateway.py)） |
| 子 Agent 传递秘密 | 已完成 | `test_secret_or_forged_input_never_creates_child_model`（[`test_analysis_delegation_boundary.py`](sujie/tests/test_analysis_delegation_boundary.py)） |
| 三态 ask/allow/block | 已完成 | DSL `allow/ask/block/hard_block`；ASK 审批绑定、执行前复核（[M12](sujie/docs/M12_AUTONOMOUS_APPROVAL_AND_BUDGET.md)、[`test_dsl.py`](sujie/gateway-python/tests/test_dsl.py)） |
| 运行时风险等级 | 部分完成 | 决策记录有 `risk` 字段 | 由决策反推，uncertainty 固定为 0 |

### 能力4 跨 MCP 与子 Agent 溯源

说明见 [`PROVENANCE_GRAPH.md`](sujie/docs/PROVENANCE_GRAPH.md)。演示：间接注入（Issue）→ 主 Agent → 子 Agent → 孙 Agent → 经 `operations` MCP 读 `~/.ssh` 合成密钥 → 经 `network` MCP 外发到未知域名，被 **BLOCK**（[DAG/时序图/报告](sujie/docs/provenance-demo/README.md)，`python eval/provenance_demo.py` 可复现，两次运行产物逐字节一致）。

| 子项 | 状态 | 证据 / 缺口 |
|---|---|---|
| 触发源 | 已完成 | `source` 节点：用户（TaskContract 目标/用户消息）/ 外部资源（带检测发现的 MCP 返回、网页）/ 记忆 |
| 节点链（主→子→孙 Agent、MCP） | 已完成 | `agent`（父、深度、Grant 范围）、`mcp_server`、`gateway`、`tool_call`、`decision` 节点；仅凭账本即可推断三层 Agent 树（`test_trace_only_build_infers_the_same_agent_tree`） |
| token 级来源 | 部分完成 | `span` 节点给出原文字符/UTF-8 字节/token 区间，零宽、全角、中文已测；token 为确定性 `sujie-simple-v1` 分词，非模型 token ID；Base64 等解码后载荷只到 Artifact 级 |
| 调用详情 | 已完成（离线）/ 部分完成（控制台） | `ProvenanceRecorder` 保留参数，导出前统一脱敏（私钥、token、SECRET 原文及其 URL 编码均替换为长度+哈希）；控制台尚未接 Recorder，显示规范化效果+参数哈希 |
| 影响范围 | 已完成 | `impact` 节点按本地文件/凭据存储/网络/Git/记忆分类，标 affected/pending/prevented |
| DAG 可视化 | 已完成 | Mermaid + Graphviz DOT/SVG，攻击路径标红；控制台新增“攻击链路溯源”页 |
| 时序图 | 已完成 | Mermaid `sequenceDiagram` 与纯 Python 泳道 SVG（User / 各 Agent / Gateway / 各 MCP） |

### 能力5 对抗鲁棒性（`detection_v2`，运行时默认，见[检测器版本](sujie/docs/DETECTOR_VERSIONS.md)）

| 绕过类别 | 状态 | 证据 |
|---|---|---|
| 多语言混排/Emoji | 已完成（规则） | 中/日/俄/德/西/法覆盖指令及繁简折叠（[`zh_rules.py`](sujie/gateway-python/src/sujie_gateway/zh_rules.py)） |
| Unicode 同形字/零宽/全半角 | 已完成（规则） | NFKC、Cf 过滤、西里尔同形映射 |
| 指令拆分/多轮 | 部分完成 | 单文本片段重组；真实多轮追加未闭环 |
| 注释符拼接 | 已完成（规则） | HTML 注释、伪角色分隔符、MCP `<IMPORTANT>` 标记 |
| 字符编码 | 已完成（规则） | 有界 percent/HTML/\\u/Base64 字段解码 |
| 上下文稀释 | 已完成（有界） | 1,000,000 字符内完整扫描，超限拒绝而非截断（`ScanLimitExceeded`） |
| 语义伪装 | 部分完成 | 伪造审批+敏感效果、角色扮演规则；公开 jailbreak 类召回低 |

七类×三来源合成矩阵（42 条，开发集）：召回 21/21、误报 0/21（`python eval/run_bypass_matrix.py`）。公开数据集 held-out（从未用于调参，`python eval/run_public_injection.py --full --split heldout`）：

| 来源 | 召回 | 精确率 | 正常样本误报率 |
|---|---|---|---|
| deepset/prompt-injections | 0.217 | 1.00 | 0 |
| Lakera/gandalf_ignore_instructions（仅攻击） | 0.688 | 1.00 | — |
| mcp-tool-poisoning | 0.750 | 1.00 | 0 |
| xTRam1/safe-guard | 0.606 | 0.975 | 0.71% |
| agent-safety-bench-zh | 0.158 | 1.00 | 0 |
| pi-benchmark-chinese（繁体） | 0.088 | 1.00 | 0 |
| JailBench（独立来源） | 0.200 | 1.00 | — |
| Safety-Prompts 中文正常文本 | — | — | 0.23% |
| **全部 held-out** | **0.306** | 0.982 | 0.37% |
| **中文 held-out** | **0.198** | 0.984 | 0.23% |

### 交付物清单

| 交付物 | 状态 | 位置 |
|---|---|---|
| 部署说明 | 部分完成（需按当前版复核） | [`部署说明-溯界.md`](competition/submission/部署说明-溯界.md)、[`sujie/deploy`](sujie/deploy) |
| 整体设计文档 | 部分完成（报告基线为 `99cba60`，未含 PR #20/#21） | [`作品报告-溯界.md`](competition/submission/作品报告-溯界.md)、[LaTeX](competition/submission/latex)、[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 源码 | 已完成 | [`sujie/`](sujie) |
| 测试样例及测试流程说明 | 部分完成（需补 `detection_v2` 与公开数据集评测流程） | [`测试样例与流程说明-溯界.md`](competition/submission/测试样例与流程说明-溯界.md)、[`sujie/eval/cases`](sujie/eval/cases) |
| 原创性声明 | 部分完成（待全员签名） | [`作品原创性声明-溯界.md`](competition/submission/作品原创性声明-溯界.md) |
| 加分：CVE 复现 | 未完成 | 仅有 CVE-2025-53773 防御场景（`.vscode/settings.json` 写入被硬阻断，见能力3）；无真实版本复现，CVE-2024-49035 未涉及 |

### 缺口与下一步（截止 2026-10-22）

1. **P0 定稿材料**：用当前提交重建作品报告/PDF 与测试流程说明，补入 PR #20、`detection_v2` 指标与敏感写入硬策略；完成匿名检查、全员签名与上传回执。
2. **P0 风险等级**：在 `M1Policy.decide` 给出独立风险依据（效果类别、来源发现、数据等级），不再由决策反推。
3. **P1 执行前对齐**：在 ALLOW/ASK/BLOCK 前调用对齐评估并记录结论，至少覆盖“读后编码外发”“读后委派”两种组合。
4. **P1 CVE-2025-53773 封闭复现**：用合成 IDE 工作区演示“注入→写 `.vscode/settings.json`→被硬阻断”的端到端链路与溯源图。
5. **P1 溯源收尾**：控制台接入 `ProvenanceRecorder` 展示可读参数；token 区间对接模型分词器；把溯源图纳入作品报告与测试流程说明。
6. **P2 检测泛化**：语义检测统一编排（规则快速通路+任务感知分类），提升角色扮演/中文 agent 注入召回；真实多轮追加 API 与检索式记忆。


> **2026-10-19 实施首批：**[结构化工具返回来源接入](sujie/docs/M26_RESULT_SOURCE_STATUS.md)已补嵌套/数组/额外字段和字段名扫描、完整结构来源及审批续跑绑定；新增21项专项，本地全量1046通过/1跳过，跨平台Python CI待确认。其余审计缺口继续保留。

> **2026-10-19 最新主线审计：**以 `fb6e6e4`（含PR #18）核对源码与五项赛题要求，见[逐项完成度、反例与补强工作包](competition/docs/MAIN_CAPABILITY_AUDIT_2026-10-19.md)。本轮97项定向回归通过、1项资产缺失跳过；该基线Ubuntu全量通过，Windows仍有1项终态等待失败。报告通过不表示五项能力或最终交付已全部验收。

> 2026-10-18：新增[聊天控制台](sujie/docs/CONSOLE_CHAT_CHECKPOINT.md)，含实现、数据处理变化及验证边界；下文旧阶段记录保留。

> **2026-10-18 交付进度：**M22—M25 代码已整合，M25 LaTeX 作品报告已通过 [PR #15](https://github.com/jiapengLi11/AgentGuard/pull/15) 合入 `main`。报告为17页、358882字节，已通过XeLaTeX构建和全页版式审阅；见[交付状态与剩余事项](competition/submission/LATEX_DELIVERY_REVIEW.md)。原 Release 仍为M21快照。各阶段实验保留原版本身份，本次代码整合验证见 [main 同步记录](docs/GITHUB_MAIN_SYNC_2026-10-18.md)。

面向大模型智能体提示注入与工具滥用的运行时安全网关，用于中国研究生网络安全创新大赛题目5。模型提出动作，可信 Host/网关按任务契约、Grant、来源用途和 DSL 实施 **ALLOW / ASK / BLOCK**，记录真实副作用。

更新：2026-10-18，M25已实现同事实观察性比较和三来源有限代表；脚本48格与来源14格通过独立核验，完整离线HTTP状态以阶段总记录为准。**比赛主线为 `sujie/`；根目录 `agentguard/` 是历史v0.1原型。**

## 交接入口

- **作品交付：**[LaTeX工程与编译说明](competition/submission/latex/README.md) / [交付验收清单](competition/submission/LATEX_DELIVERY_REVIEW.md) / [PDF构建产物](https://github.com/jiapengLi11/AgentGuard/actions/runs/39140488105)（登录GitHub后下载 `sujie-m25-latex-review`）。正式宋体、签名、M25原始证据移交、新环境运行和录屏仍待完成。
- [M25与项目总体报告](competition/docs/M25_AND_OVERALL_REPORT_2026-10-18.md) / [M25阶段记录](sujie/docs/M25_STATUS.md)。
- [同事实比较协议与边界](sujie/docs/M25_MODEL_COMPARISON.md) / [三来源代表](sujie/docs/M25_SOURCE_BYPASS.md)。
- [M24实施与验收](sujie/docs/M24_STATUS.md)：四候选参数化、独立核验与生命周期修复；v1结果和最终v2分开记录。
- [下一阶段安排](sujie/docs/M25_NEXT_STEPS.md)：同事实模型比较、来源绕过、演示和匿名交付；[材料证据骨架](competition/docs/COMPETITION_EVIDENCE_OUTLINE_2026-10-18.md)。
- [M23阶段验收](sujie/docs/M23_STATUS.md)：657项回归、40个参数化开发单元、35个固定提议单元与Linux四链历史证据。
- [M22第一批实施记录](sujie/docs/M22_FIRST_BATCH_STATUS.md)：Mac修复、IOC开发修复、任务登记与共同运行器的本轮证据及边界。
- [当前执行计划](competition/docs/NEXT_ACTION_PLAN_2026-10-16.md)：实施顺序、准入条件、正式评测与交付安排。
- [已完成工作简明汇总](sujie/docs/COMPLETED_WORK_SUMMARY.md)：已有成果、最近验证与剩余缺口。
- [项目交接手册](sujie/docs/PROJECT_HANDOFF.md)：安装、启动、预算、代码、证据保存与接手顺序。
- [全部文档索引](sujie/docs/DOCUMENT_INDEX.md)：每份指南/记录的适用阶段。
- [当前状态](sujie/docs/F2_IMPLEMENTATION_STATUS.md) / [官方能力证据矩阵](sujie/docs/TOPIC5_EVIDENCE_MATRIX.md) / [F3计划](competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md)。

四类新增业务在M21验收后曾停止；2026-10-16已按用户要求恢复第一批修复与离线校准。F3整体、正式独立任务冻结与云主比较仍未完成。旧设计的技术栈、数量目标和排期不能视为已交付或官方指定条件。

## 已实现的范围

| 范围 | 当前结果 |
|---|---|
| 授权与执行 | 九类契约、真实stdio MCP、效果映射、DSL、三态、审批绑定、执行前复核与工具版本检查 |
| 来源与模型 | Artifact/DAG、保守传播、输入快照/本地token、请求/回应保护、固定百炼模型及共享预算 |
| 工具与长链 | 封闭文件/HTTP/进程/Git、IOC/Git自主ASK续跑、实际子/孙对话与两个独立Memory会话 |
| 业务与信息保全 | 13个开发profile；时间线/Issue/附件/知识冲突四新业务；报告可选无工具字面引用核验 |
| 操作者与证据 | Python控制面、Vue任务/审批/来源/序列/影响/导出、五配置开发比较与离线重算 |

M25全量原始日志记载 **1022 passed / 1 warning（759.38秒）**，Ruff及216文件格式检查通过；用户中断后未取回进程退出码，检查状态与证据见[M25记录](sujie/docs/M25_STATUS.md)。脚本比较48格/14配对：正常执行48、合法业务完成46、实际危险效果2（Git注入的unsafe/strong-static）；来源代表14格/7配对：业务完成14，3次不许可的本地标记写入均在unsafe下，Full为0。以上均为已暴露开发输入与脚本/封闭传输校准，云调用0，不是模型ASR。

M24历史最终v2全量 **893 passed / 1 warning**，202文件格式通过；四候选80格、两业务40格、35固定提议和Linux六链通过独立核验。Memory生命周期证据缺口已修复，v1结果与反例保留。全部为本地开发校准，云调用0，不作比赛ASR或正式模型比较，见[M24记录](sujie/docs/M24_STATUS.md)。前端源码未改，M23的Vue构建和M22/M21原结果保留原版。

## 快速开始（Windows PowerShell）

需要Python3.12；前端Node20.19+或22.12+，Git业务另需Git。安装和首次分词器准备需网络或已核验离线资源。

```powershell
Set-Location sujie
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe dev.py prepare-tokenizer
Push-Location console-vue
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe dev.py demo
.\.venv\Scripts\python.exe dev.py console
```

Linux/macOS改用 `.venv/bin/python`。打开 `http://127.0.0.1:8765`，使用本机 `.control-runtime/operator-token.txt` 登录。无密钥时运行固定动作/确定性演示；云配置及自定义端口直接用 `control-plane-python/run_console.py`，详见[手册](sujie/docs/PROJECT_HANDOFF.md)。`dev.py console` 不透传参数，`.env.example`是假值占位。

原本地M22—M25接手环境曾在**仓库根目录**建立`.venv/`，使用`./.venv/bin/python sujie/dev.py check`；原`sujie/.venv/`是保留的Windows环境。这些环境与前端依赖目录均不随Git上传，新机器须按上文独立安装。历史环境说明见[M22记录](sujie/docs/M22_FIRST_BATCH_STATUS.md)。

现有8765实例不会自动加载新代码，先导出需保留的任务再协调重启，或使用其他空闲端口。关闭任务/服务会清理临时工作区；持久预算账本不表示任务/审批可跨重启恢复。

## 目录与验证

| 目录 | 定位 |
|---|---|
| `sujie/` | 比赛代码、契约、Host/控制面、Vue、MCP、执行器、评测与阶段记录 |
| `competition/docs/` | 历史设计与F2/F3计划；目标不等于实现 |
| `competition/research/` | 当时的官方/调研原始快照，保持原样 |
| `agentguard/`、根目录`tests/`/`benchmark/` | 历史v0.1代码、测试与样例 |
| 根目录`docs/` | 当前导航和历史原型边界说明 |

从 `sujie/` 运行 `python dev.py check` 做本机静态/格式/pytest验证；Vue构建另行执行。CI配置已写，不声称远端已通过。报告多数在忽略目录，交接不能只复制可见源码。

## 安全与剩余工作

合成封闭研究原型；Host、执行器和宿主可信。子Agent同Host，本地token不是云内部token，审批没有跨崩溃exactly-once。M24六链已在受限单容器完成，完整工具/角色隔离及性能尚未验收。

真实模型主比较所需的新协议、资源准入、未见输入与统计、有效消融，完整三来源七绕过、历史裸分类入口统一、新版整体隔离性能、材料与现场复现仍待完成。当前主/子/Memory/引用分析已绑定有效HTTP JSON请求体与响应摘要，范围见[M23](sujie/docs/M23_EFFECTIVE_MODEL_BINDING.md)。M25的48格脚本比较已运行；离线HTTP整矩阵状态见[M25记录](sujie/docs/M25_STATUS.md)，真实云CLI仍关闭。[下一阶段安排](sujie/docs/M25_NEXT_STEPS.md)列明后续准入与退出条件。不要把脚本/测试/变体数量替代独立任务数，或把未提出危险动作记为网关拦截。

[贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md) · [依赖与许可](sujie/docs/DEPENDENCIES.md) · [MIT](LICENSE)
