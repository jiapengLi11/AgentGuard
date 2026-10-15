# M2 来源继承与检测样例进度

> **2026-10-15 交接说明：** 历史M2快照。控制台、模型快照/本地token、实际子孙对话、版本Memory、网络/进程/Git与共同五配置已由M6–M21补入；原“缺自主循环/控制面”不能作为现状。全入口、精确转换、任意DLP、通用进程隔离仍有缺口，旧容器HTTP路径未因此自动升级。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

## 已实现

- 可信 Host 可调用 `M1Gateway.record_model_output` 登记摘要、自由改写或序列化后的内容。来源父集合取网关实际向模型暴露的 Artifact，不能由模型文本指定。派生信封始终保持 `DATA_ONLY` 与 `UNTRUSTED`，机密级别取父节点最高级，允许用途取交集、禁止用途取并集；自由生成不伪造字符级映射。
- `CONTENT_SUMMARIZED` 事件和派生 Artifact 进入可信 Trace。基于派生内容的直接复制外发沿用执行前来源约束；同一份摘要仍可写入合同允许的本地报告。真实 MCP 端到端测试覆盖“证据→摘要→外发拦截”和“摘要→本地报告”。
- 新增版本化的 14 条合成检测样例，包含七种绕过类型的代表性攻击和七条正常／危险证据对照。`python dev.py eval-detection` 输出固定数据集哈希、逐例结果、混淆矩阵和分母；原始报告保存在 `eval/reports/detection_v1.report.json`。
- 新增纯策略决策基准脚本 `python dev.py bench-policy`，固定 5000 次决策、100 次预热，记录运行环境和 P50/P95/P99。此数值不含 MCP、模型、Schema 构造、审批或审计 I/O。
- 新增一个白名单可信脱敏器：只从长度受限、非 CONFIDENTIAL/SECRET 的原始 MCP 证据中提取合法、全球可路由且非组播的 IPv4 地址，去重排序并限制最多 20 个，输出固定 `PUBLIC_IPV4_IOCS` 格式。脱敏器自身计算正文，不接受模型指定的脱敏结果；派生 Artifact 保留父来源，但仅对这个固定输出解除 `TRANSFER` 禁令，并仍由合约与 ASK 审批控制外发。端到端测试证明原文拒绝、脱敏列表经审批后恰好外发一次。
- 读过外部证据后的外发必须与网关登记的可转移 Artifact 正文完全一致。可信 Host 可登记独立固定内容；未登记的模型改写会以 `EGRESS_SOURCE_UNREGISTERED` 拒绝。登记入口未暴露在 Agent HTTP API。此约束只针对当前 `data.transfer` 效果。
- 本地文件写入将正文哈希绑定到其保守父 Artifact；再次读取时，仅在实际文件正文哈希相同的情况下恢复父来源。可选 SQLite 证据库保存文件绑定和 Artifact，跨两个网关会话的“证据→摘要→本地报告→再次读取→外发拦截”已有真实 MCP 测试。该库应按工作区隔离；现阶段会加载库中的旧 Artifact 元数据，尚无生产级保留期、加密和并发一致性。
- 新增真实 stdio Memory MCP Server 的 `read/write`。两者分别映射 `memory.read/memory.write` 效果与可信合约目的；写入正文哈希和父来源与文件相同地存入证据库。端到端测试在新会话恢复 Memory 来源，读取时重新检测为 `attack_source=MEMORY`，并拦截污染摘要外发。
- MCP Proxy 注册前扫描整个工具元数据，包括工具描述和输入 Schema 描述。两种真实恶意 Server 变体均在注册时被拒绝；每次调用仍重新取元数据并比对固定版本哈希。当前扫描是明确指令覆盖的基础规则，既可能漏掉隐晦投毒，也可能误拒包含攻击语句引用的合法工具。
- 受限 `exec` 原型提供固定 SHA-256 子进程，仅处理受控报告目录内、最多 64 KiB 的文件；Gateway 预先校验 `EXECUTE` 目的、`exec` 效果和 Grant。真实 stdio 端到端测试证明默认拒绝、明确授权放行并返回实际文件哈希，试图读取秘密文件被适配器与工具双方拒绝。这不是任意命令沙箱。
- 本地 Git 靶场新增无参数 `git.push_report`，封存源仓库和本地裸远端，将 HEAD 推送到固定 `refs/heads/report`。真实 Git ref Oracle 证明默认合同禁令阻断推送；解除禁令并明确授权后才更新 ref。此工具依赖可信仓库，不适用于任意不可信 Git 配置或钩子。
- 可信 Host 可用 `spawn_child` 派生共用同一 Trace 的子 Gateway：先验证父子 Grant 收窄、完整预算、任务合同及 `DELEGATE` 目的，再预留子任务预算。子 Gateway 只能以子 Grant 调用真实 MCP 工具；父 Host 通过 `adopt_child_artifact` 接收保留原始父节点的 Artifact。端到端测试覆盖子权限阻断、子读取证据→子摘要→父侧外发阻断，以及再次委派超预算。它是逻辑子 Agent 门禁与来源链原型，尚未接入独立子进程或自主 Agent 循环。

## 当前可复现结果

在 `detection-v1-synthetic-smoke` 上，基础规则检测 TP=5、FN=2、FP=1、TN=6。分片和语义伪装样例漏检；引用攻击句子的培训材料误报。该集合很小且由开发者构造，只用于暴露基础规则的能力边界，**不是比赛防御成功率、Execution ASR 或真实模型结果**。

本机 Windows 11 / Python 3.12.2 的 5000 次纯策略决策 P50=0.0547 ms、P95=0.08243 ms、P99=0.164311 ms，原始环境与数值见 `eval/reports/policy_latency_windows.json`。它不能代表端到端网关延迟或其他机器的性能。

## 未完成的关键链路

- `record_model_output` 当前只在可信 Host 内部调用；容器 HTTP Agent 尚未接入强制的输出登记。当前外发会拒绝未登记正文，但不能据此声称跨文件写入、记忆、子 Agent 或其他工具的自由改写都无法绕过来源传播。需要把所有模型输出及下游工具参数绑定到受控 Host Hook，并验证不能绕开。
- 白名单 IPv4 提取器只适用于公开地址 IOC，不对任意文本脱敏，也不证明提取出的 IOC 本身适合在所有任务中外发。它是受限场景下的安全续做原型，外发仍需任务显式允许和可信审批。
- 对任意截取、编码、翻译和分片外发的细粒度 DLP 尚未实现；子 Agent 当前仅支持单进程逻辑子 Gateway 和显式 Artifact 交接，缺少独立运行时、撤销传播与完整子 Agent 循环。Memory 的跨会话恢复仅覆盖同一受控 SQLite/工作区绑定，不代表任意外部记忆系统。固定 exec 工具尚未具备设计文档要求的无特权、无网络、资源受限容器执行隔离。
- 文件来源恢复只覆盖经当前网关写入的受控工作区文件；外部进程改写、复制到其他存储和跨工作区迁移没有完整来源证明。内容哈希不符时不引用旧父节点，新读取内容仍按不可信 MCP 结果处理。
- 三类来源、七类绕过的系统测试、真实模型多次重复、控制面、可视化、性能和消融评测仍需继续。

## 验证命令

```powershell
cd sujie
.\.venv\Scripts\python.exe dev.py check
.\.venv\Scripts\python.exe dev.py demo
.\.venv\Scripts\python.exe dev.py eval-detection
.\.venv\Scripts\python.exe dev.py bench-policy
```
