# 项目交接手册

更新：2026-10-15。实现基准为 M21 及其协议索引修正；本轮仅整理文档。

## 1. 先读什么、以什么为准

1. [已完成工作简明汇总](COMPLETED_WORK_SUMMARY.md)：快速掌握已有成果和结论。
2. 本手册：安装、运行、代码入口、证据保存和交接约束。
3. [当前工作包状态](F2_IMPLEMENTATION_STATUS.md)与[官方能力证据矩阵](TOPIC5_EVIDENCE_MATRIX.md)：尚未验收的范围。
4. [F3 计划](../../competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md)：后续目标与依赖；其制定时的现状、日程和指标不是当前成绩。
5. [全部文档索引](DOCUMENT_INDEX.md)：区分当前指南、阶段记录、历史原型和设计目标。

当前实现事实以代码和对应阶段的原始证据为依据；历史记录保留当时版本。原始设计并非当前全部实现，旧任务清单也不是接手后的自动执行指令。用户最后一次开发范围为“四类业务实现后先停止”，已完成；**本次授权为文档更新，剩余开发尚未恢复**。

## 2. 项目身份和完成边界

溯界针对题目5的提示注入与工具滥用：模型提出工具动作，可信 Host/网关按任务契约、Grant、来源用途和 DSL 决定执行、审批或拒绝。

| 路径/组件 | 当前定位 |
|---|---|
| `sujie/` | 比赛实现主线，所有下文命令默认在此目录执行 |
| 根目录 `agentguard/`、`tests/`、`benchmark/` | 历史 v0.1；其测试、环境变量和入口不能代替比赛版验证 |
| `control-plane-python/` + `console-vue/` | 当前可运行操作者入口；同源本机服务 |
| `control-plane-java/` | 仅说明目录；Java/Spring/MySQL 未实现，不是运行依赖 |
| `deploy/m1.compose.yaml` | 历史 M1 确定性容器链路；未覆盖当前全部模型、子 Agent 与新增工具 |
| `deploy/compose.yaml` | M0 历史占位，不作部署/隔离证据 |

已实现的 13 个开发 profile：

| profile | 任务结果 | 专项说明 |
|---|---|---|
| `report` | 读取合成告警并保存报告；可选无工具证据分析 | [M20](M20_VERIFIED_EVIDENCE_QUOTATIONS.md) |
| `ioc-transfer` | 提取公开 IPv4 IOC，经 ASK 提交到封闭 Receiver | [M12](M12_AUTONOMOUS_APPROVAL_AND_BUDGET.md) |
| `web-report` | 实际封闭 HTTP GET，核查网页事实和出处 | [M14](M14_NETWORK_AND_WEB_WORKFLOW.md) |
| `artifact-verify` | 实际注册程序进程核验构件摘要并保存报告 | [M15](M15_STRUCTURED_EXECUTION_AND_ARTIFACT.md) |
| `git-review` / `git-publish` | 检视保持远端不变 / 审批发布确切 commit 与 ref | [M16](M16_GIT_DELIVERY_AND_APPROVAL.md) |
| `delegated-report` | main→review→verify 真实对话与工具复核 | [M17](M17_ACTUAL_ANALYTICAL_AGENTS.md) |
| `memory-review` / `memory-update` | 新会话核对已存原文 / CAS 追加版本后复读 | [M18](M18_CROSS_SESSION_MEMORY.md) |
| `event-timeline` | 四源读取后按主体/session/闭区间筛选并跨源排序；有界 Host 查询 | [M21](M21_FOUR_BUSINESS_WORKFLOWS.md) |
| `issue-triage` | 依次核对损失优先级、影响/时长阈值，输出 P0/P1/P2 及负责人/出处 | [M21](M21_FOUR_BUSINESS_WORKFLOWS.md) |
| `attachment-audit` | 邮件、发票 JSON、明细 CSV 按整数分核对金额/币种/差额 | [M21](M21_FOUR_BUSINESS_WORKFLOWS.md) |
| `knowledge-reconcile` | 选 approved 中最大 revision；说明高版草稿等排除原因 | [M21](M21_FOUR_BUSINESS_WORKFLOWS.md) |

`clean`、`injected` 为正常/注入开发场景；`quoted` 是要求保留危险原文的合法引用场景，仅四个 M21 profile 支持该场景。M20 的可选分析工具属于 `report`，与 M21 的 `quoted` 场景不是同一开关。profile、场景、攻击模板、重复次数和独立任务数必须分别统计。

## 3. 新机器安装与无密钥启动

需要 Python **3.12.x**、Node **20.19+ 或 22.12+**；Git 业务还需要 PATH 中可执行的 Git。当前检查解释器为 Windows Python 3.12.2；旧文档中的其他补丁版本是历史环境。不要拷贝旧 `.venv` 或 `node_modules` 充当可移植环境。

Windows PowerShell，从仓库根目录开始：

```powershell
Set-Location sujie
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe dev.py prepare-tokenizer
Push-Location console-vue
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe dev.py demo
.\.venv\Scripts\python.exe dev.py console
```

Linux/macOS 使用 `.venv/bin/python`。安装包、首次分词器下载和前端安装需要网络或预先核验的离线资源；**无 API 密钥模式不等于新机完全离线安装**。
`prepare-tokenizer` 只下载固定 revision 的公开 JSON，不下载模型权重；运行时不自动补下载。缺失资产会标注 `UNAVAILABLE`，不能声明 token 映射正常。清单为 `assets/tokenizer/qwen3-local-manifest.json`，缓存位于 `model-cache/`；资产及许可仍需纳入正式交付整理。

打开 `http://127.0.0.1:8765`，本机查看 `.control-runtime/operator-token.txt`，把本次操作者凭据粘贴到页面。不要把内容写入文档/日志/提交包。凭据在页面内存中保存，刷新后需重新登录；每次启动生成新凭据。服务只绑定 loopback。

未配置模型时可运行确定性演示、手动固定动作和离线核验；自主云模型任务需要下一节的 Provider。`dev.py console` 不透传参数，自定义端口或云配置必须直接运行启动脚本。

### 已存在的 8765 服务

交接时旧 8765 实例未由本轮重启，已有用户任务未清理。旧进程不会自动加载源码变化；新版静态资源也不能证明旧后端已升级。先导出需要保留的任务，协调停止原进程再启动；可用其他空闲端口验证，例如 `--port 8767`，不要为释放端口强杀未知进程。

## 4. 云模型启动与预算

当前 Provider 为阿里云百炼兼容接口，固定 `qwen-plus-2025-12-01`。用户已确认平台启用“免费额度用完即停”；新接手账号需自行核对可用模型、额度和此设置。本地预算不保证供应商账单上限，快照/免费资格也不作为永久承诺。

先完成第3节安装/构建；凭据 CSV 通过私密渠道另行交接，置于仓库外。下列路径仅为占位，应替换为接手环境已有文件：

```powershell
.\.venv\Scripts\python.exe control-plane-python/run_console.py `
  --port 8767 `
  --credentials-file 'C:\private\bailian-credentials.csv' `
  --model-budget-file '.control-runtime/model-budget-8767.sqlite3' `
  --max-provider-requests 60 --max-reservation-units 1000000
```

此端口凭据文件为 `.control-runtime/operator-token-8767.txt`。CSV 由可信 Provider 加载，不经页面上传、不传 MCP、不进入模型消息或导出。`.env.example` 为早期占位，启动器不读取其假密钥/MySQL 配置。

| 预算/生命周期 | 当前约束 |
|---|---|
| 服务共享账本 | CLI 默认持久化到 `.control-runtime/model-budget-<port>.sqlite3`；默认60请求/1,000,000预留单位 |
| 任务共享预算 | 默认12请求/200,000预留单位；子角色共用，不是每角色各得一份 |
| 主 Host | 最多6轮模型/10次工具提议；Memory/子角色另有更小限额，仍受共享总量约束 |
| 缺少用量/失败/取消 | 保留预留；崩溃遗留 PENDING 不自动退款；预留单位不是 token 或真实账单 |
| 预算配置变化 | 同账本 scope 配置不匹配会拒绝；新实验可明确建立新账本，不删除旧账本绕过累计限制 |
| 任务状态 | 同服务仅一个自主运行；任务临时，关闭任务/服务会清理工作区；共享预算持久化不等于任务/审批持久化 |

新建全新任务后选择模型运行；IOC/Git 待审时先核对预览，**批准不执行，提交才执行**。提交再次核对输入、工具、合同/Grant、策略、状态和来源；确认丢失标 UNKNOWN 并停止，不自动重发。拒绝组的协议检查通过不等于原始外发目标完成。

## 5. 代码定位

以下路径相对 `sujie/`，类/文件名中的 M1 为沿用命名，并非当前只实现 M1。

| 入口 | 修改/排查范围 |
|---|---|
| `contracts/schemas/`、`gateway-python/src/sujie_gateway/contracts.py` | 九类序列化对象、不变量、包0.2/载荷1.0；摘要清单不能随手重生成 |
| `gateway-python/src/sujie_gateway/m1_runtime.py` | `StdioMCPProxy`、`M1Policy`、`M1Gateway`、授权/审批/来源/Trace 主链 |
| `gateway-python/src/sujie_gateway/model_context.py`、`sequence_alignment.py` | 输入快照/区间、出口规则、可见计划与实际效果关联 |
| `demo-agent/sujie_demo_agent/bailian_agent.py` | Provider 与有界工具调用 Host；不是仅旧 LangGraph 测试图 |
| 同目录 `protected_model.py`、`model_budget.py`、`tokenizer_mapper.py` | 角色来源包装、请求/回应检查、共享账本、本地分词映射 |
| 同目录 `delegated_agent.py`、`evidence_analysis.py`、`business_workflows.py` | 实际子/孙对话、无工具引用分析、四业务资料/规则 |
| `control-plane-python/run_console.py`、`sujie_control/api.py` | 实际 CLI、独立认证 HTTP 入口；无评测基线切换接口 |
| `sujie_control/runtime.py`、`profiles.py`、`model_runner.py` | 任务临时环境、冻结模板、模型协调与限额 |
| `sujie_control/memory_workflow.py`、`timeline_query.py`、`business_oracles.py` | 两会话记忆、有界窗口查询、Host 事实/读取/未改源核验 |
| `mcp-servers/`、`sandbox/` | stdio 工具与实际 HTTP/进程/Git/版本化 Memory 执行器 |
| `console-vue/src/App.vue`、`types.ts` | 控制台操作、状态/脱敏 DTO；前端不是授权来源 |
| `eval/`、`tests/`、`gateway-python/tests/`、`contracts/tests/` | 校准/实验/重算与回归；原始报告和协议不可追溯篡改 |

当前工具目录还包括 `network-server`、`execution-server`、`git-delivery-server`、`versioned-memory-server`；旧 `git-server`/`memory-server` 保留早期测试用途，不能把旧工具能力等同新版业务。不是每个 profile 都启用全部工具，也不是只有四个 MCP Server 文件。

## 6. 验证、结果与证据保全

### 可执行的无云检查

从 `sujie/` 执行；不会因下面命令主动调用百炼：

```powershell
.\.venv\Scripts\python.exe dev.py check
.\.venv\Scripts\python.exe -m pytest tests/test_business_workflows.py tests/test_evidence_analysis.py -q
.\.venv\Scripts\python.exe eval/verify_runtime_validation.py eval/reports/runs/four_business_m21_scripted_v3
```

`check` 含 ruff 检查、格式检查和全部 pytest；时长与机器相关。本轮为文档更新，未重跑全量回归或云模型。要生成新的四业务确定性校准可使用下列命令，输出目录必须是新的；没有 `--credentials-file` 时使用脚本模型：

```powershell
.\.venv\Scripts\python.exe eval/run_business_validation.py `
  --protocol-file eval/protocols/four_business_workflows_v2.json `
  --out-dir eval/reports/runs/handoff_business_new
```

此命令是复现入口，不能把文档中列出的命令当成本轮已执行。增加凭据会进入云验证，接手人应先确定新协议、预算和失败保留规则。`dev.py bench-gateway` 使用固定历史输出路径，保留旧记录时不要直接重跑覆盖，应直接检查其脚本参数后选新输出。

### 当前可引用证据

所有目录相对 `eval/reports/runs/`。完整版本细节以专项记录为准。

| 记录 | 事实及解释 |
|---|---|
| `four_business_m21_scripted_v3/summary.json` | 16/16脚本业务；0云。84文件源码归档 SHA-256 `f6f1fbb5fd3a42791cb48b1830d768a8f166318a25a323a3a24645981cfcd32d` |
| 同目录 `checks.json` | 查询修复前479 passed/2 skipped/1 warning；修复后52专项；166文件格式与Vue构建通过；无最新浏览器布局验收 |
| `four_business_m21_model_v1/summary.json` | 云首轮3/4；时间线失败保留；15请求/24,144tokens |
| `four_business_m21_timeline_model_v2/summary.json` | 修复时间线Q完成；3请求/5,645tokens；84文件归档 SHA-256 `3854649fc747b071ba9393453aa883a42bf76544253bc46f5237744df01d2b26` |
| `common_real_model_m19_v1/summary.json` | 五配置×两个开发任务单元，7/10完成；31请求/25,005tokens。三个IOC失败只读未发送，无阻断归因 |
| `evidence_quotes_m20_cloud_v1/summary.json` | 脚本主流程+一次云分析，353tokens；引用核对，不是全程自主云任务 |

M21 协议身份：最初脚本 v1 为512输出上限，已从源码归档恢复原字节；默认 `four_business_workflows_v2.json` 为1024。云首轮曾使用同名修改过的开发协议，原报告/内嵌协议/摘要/失败均保留；审计在 `four_business_m21_model_v1/protocol-identity-audit.json`。时间线修复使用独立协议，随后索引整理只影响两项元数据，见其 `source-verification-after-protocol-index-fix.json`。不能把旧报告改名或改分当成当前版本新跑。

离线核验字段分开解读：原始摘要/图/序列一致性、`recorded_validation_passed`、`current_sources_match` 不是同一结论；有的汇总 `ok` 还包含原运行是否通过，失败实验可能 `ok:false`。当前源码不匹配旧归档不自动说明证据损坏；一致性通过也不等于实验全成功、签名真实性或 ASR。

### 必须随项目另行移交的本地产物

- 文档链接到的 `eval/reports/` 原始报告、脱敏导出、实际合成结果、`runtime-sources` 与 manifest；多数被忽略，单纯复制 Git 可见文件会缺失。
- 固定协议 `eval/protocols/`、数据版本与外部来源/许可、依赖锁、分词器清单与核验后的资产；离线 wheel/镜像若采用，另附其来源和完整摘要。
- 需要保留的用户任务先从控制台导出；临时任务正文、审批与 MCP 生命周期不会因预算账本持久化自动保存。
- API CSV、操作者 token、个人环境文件通过独立私密渠道处理，不装入公开源码/证据包。不要把整个 `.control-runtime`、虚拟环境或个人聊天文件夹打包公开。

M9 冻结四文件保持原样：`demo-agent/sujie_demo_agent/semantic_detector.py`、`gateway-python/src/sujie_gateway/detection.py`、`eval/task_aware_protocol.py`、`eval/run_frozen_task_aware.py`；摘要见 `eval/protocols/task_aware_holdout_v1.json`。后续算法另建版本，已暴露验证/测试不能重新称为未见留出。

## 7. 尚未完成及建议接手顺序

下表保留剩余工作，**不是本轮新增执行授权**；恢复开发时按实际资源调整。

| 顺序 | 工作与验收要求 | 当前限制 |
|---|---|---|
| 1 | 登记独立基础任务/Oracle、固定 C正常/A攻击/Q合法危险引用/R授权高风险与五配置公平条件 | 13开发profile不等于正式12任务；288内部计划运行未执行 |
| 2 | 分析 M19 IOC 合法任务失败，在开发数据修复后再冻结主比较 | 不以筛选成功运行替代失败记录，不将无危险提议算阻断 |
| 3 | 补全上下文三入口、所有实际模型角色、完整有效请求配置及返回证据；完善序列/跨轮分级语义 | 当前部分字面/转义与保守继承；历史分类/评测入口未全统一 |
| 4 | 补三来源×七绕过矩阵、敏感目录/平台效果矩阵、信息保全和恢复策略比较 | 代表链成立不等于覆盖所有绕过/任意DLP/任意业务 |
| 5 | 获得 Linux 环境后验收当前完整 Host/工具/子 Agent 隔离、进程树限制及真实性能 | 用户已确认当前无可用环境；历史 M1 不代替新版拓扑 |
| 6 | 当前同版全量回归、界面操作/布局、跨机安装、脱敏证据包、匿名报告/演示/许可/提交回执 | 远端CI、正式材料及竞赛平台提交未完成 |

Java/MySQL、多操作者、策略发布、持久任务/审批、跨崩溃一致性及跨进程子 Agent 仍为未实现扩展；是否优先取决于恢复后的实际目标。公开基准只按已适配子集描述，AgentDojo 的固定包/任务元数据不是执行成绩。赛事日期、规则、云资源与价格须在实际提交/调用前重新核对官方；本手册不重新发布历史排期为最新通知。

## 8. 不可混淆的安全结论

- Host、授权/审批、来源账本、执行器和宿主环境属于可信边界；当前子/孙模型是同 Host 对话，不是 OS 隔离进程。
- 审批是动作绑定与进程内单次提交，不是跨崩溃 exactly-once；网络/推送已发生后不承诺回滚。
- 本地 token 区间不表示供应商内部聊天模板、分词、隐藏思维或因果关系；来源 DAG 和 Hash 不证明事实真实性。
- 无工具引用分析只核对字面位置与覆盖，语义标签是模型建议，引用不会解除来源限制或获得执行权限。
- 五配置共有的封闭执行器、Provider 凭据保护、预算/审批基础设施等不能算 Full 独有贡献；基线不可通过操作者 API 开启。
- 真实模型没有提出危险动作的样例，只能报告未观察到泄露，不能报告网关成功拦截；确定性故障校准不能冒充真实模型 ASR。

最后，保持用户已有任务和原始失败证据。更新实现后同步本手册、简明汇总、状态及能力矩阵；阶段报告追加新版本，不改写旧成绩。
