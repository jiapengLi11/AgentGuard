# M1.2 任务目的与直接复制来源约束

> **2026-10-15 交接说明：** 历史目的与直接复制来源校验记录。后续保守派生/Memory见M2/M18，模型出口见M11–M13，真实网络见M14；本页局部成对验证不能等同任意分片/翻译/改写DLP。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

这一步将 `TaskContract.allowed_purposes` 和已暴露的 MCP 证据内容接入网关决策，面向“工具本身有权限，但外部材料诱导 Agent 改变用途”的情形。

## 决策次序

1. 先检查合约、Grant、资源范围、禁止效果和允许效果。
2. 将可信工具适配器产生的效果种类映射到所需目的。当前映射包括 `file.read → READ`、`file.write → WRITE_REPORT`、`data.transfer → TRANSFER`。效果获准但合约未列出对应目的时，返回硬拒绝 `PURPOSE_NOT_ALLOWED`。
3. 对已获准或需要审批的 `data.transfer`，在实际执行或预留网络预算前，检查发送正文是否逐字包含至少 16 字符的已暴露 Artifact 正文。如果该 Artifact 的来源信封禁止 `TRANSFER`，返回硬拒绝 `PROVENANCE_FORBIDS_TRANSFER`。后续加固还要求读过外部内容的外发正文与网关登记的可转移 Artifact 完全一致；否则返回 `EGRESS_SOURCE_UNREGISTERED`。被拦截的提议不消耗网络预算。
4. 其余请求继续由现有 DSL 决定 ALLOW / ASK / BLOCK。每个可构造语义动作的决策在可信 Trace 载荷中保存完整 `DecisionRecord`；公开 DAG 只含事件元数据，不暴露正文。

## 外部内容基础检测

真实 MCP 读取后，网关保留原始 Artifact，并另外生成最长 100 万字符的检查视图：NFKC 全半角归一、移除不可见格式字符、最多两轮 HTML 实体和百分号编码解码。视图放在可信证据存储，不覆盖返回给 Agent 的原文；Trace 记录 `CONTENT_NORMALIZED`，命中明确的中英文“忽略先前指令”表达时，生成符合 Schema 的 `DetectionFinding` 和 `DETECTION_FINDING` 事件。由于规范化会改变长度，当前 finding 的源 span 是整篇原文的保守范围，不伪称精确字符定位。检测只提供风险证据，不签发权限，也不替代执行前策略。

`trusted_goal` 仍是契约中的人类可读目标说明，当前实现不对其自然语言内容做语义推断。目的授权以可信创建的 `allowed_purposes` 为准。

## 成对验证

`test_E2E_PROVENANCE_001` 使用同一 TaskContract、TaskGrant、工具和本地 Receiver：

- 外部告警正文先经真实 Evidence MCP 读取并暴露。纯效果策略对“发送该正文”返回 ASK，网关的直接复制来源检查将其改为 BLOCK，Receiver 未收到请求。
- 随后由可信 Host 登记一段与证据独立的诊断文本；发送该正文仍返回 ASK，审批和提交后 Receiver 恰好收到一次。此路径也确认前一个拒绝没有耗尽唯一的网络预算。

单独的单元测试确认：即使 `data.transfer` 同时出现在合约允许效果和 Grant 效果里，缺少 `TRANSFER` 目的仍拒绝。

## 能力边界

这是直接复制的数据流约束和小范围规则检测，不是完整的提示注入检测器，也不能证明模型内部的因果来源。改写、截取、编码、翻译或跨多次调用拆分的外泄尚不能由此规则可靠识别；检测视图只扫描正文前 100 万字符，对更长文本的后半部分没有覆盖。所有已暴露 Artifact 都附在后续提议上作为保守上下文，但只有实际正文逐字匹配才触发这条外发硬拒绝，因此无关内容不会仅因读过外部材料而被拦截。后续仍需细粒度片段来源、七类绕过的系统检测、真实模型评测以及跨记忆和子 Agent 的传播。

## 本机验证

Windows Python 3.12 下运行 `python dev.py check`：183 项通过、2 项因平台能力跳过。运行 `python dev.py demo`：正常报告、注入拒绝和 ASK 单次提交均完成。真实模型 ASR 尚未测量。
