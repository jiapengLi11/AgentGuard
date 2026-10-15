# 全部文档索引与交接范围

更新：2026-10-15。主线为 `sujie/`，代码截至M21，四业务后按用户要求停止。本轮只更新文档。

## 推荐阅读

[已完成工作简明汇总](COMPLETED_WORK_SUMMARY.md) → [项目交接手册](PROJECT_HANDOFF.md) → [当前工作包状态](F2_IMPLEMENTATION_STATUS.md) → [官方证据矩阵](TOPIC5_EVIDENCE_MATRIX.md) → [F3规划](../../competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md)。

## 维护口径

- 当前指南直接更新实际入口与现状；历史设计/计划/阶段验收增加各自的后续说明，保留原始数字、失败和版本。历史正文“当前/尚未/下一步”只指原阶段。
- 原67份自有Markdown文档全部更新；新增简明汇总、交接手册与本索引，共70份。下面逐一列出，避免只移交部分README。
- 官方调研快照、冻结协议、实验报告、`runtime-sources`中的历史副本文档、外部依赖/许可资产、缓存和构建产物不作为现行编辑对象。原始证据保持不变，不批量改标题/哈希/结果。
- `requirements*.txt`、锁文件、CI/工具配置属于代码/环境事实，不因“更新文档”重新生成；假值`.env.example`不是当前云配置。源码API CSV、操作者token与私人环境不纳入公开文档。
- 本轮只做文档/本地链接/证据保全核对，不重新调用云模型、重跑全量回归、重启服务或执行剩余F3任务。详细结果版本边界在M21和交接手册。

## 完整清单

路径相对仓库根目录；“阶段记录”不是当前总验收。复制项目时还应移交手册列出的忽略证据/资产，凭据另行私密移交。

本轮核对结果（本地观察，非签名验收）：原67份文档均有更新，70份现行自有文档中的332个本地链接目标均存在；官方调研快照、实验报告、协议及M9冻结实现共563份文件与整理前逐字节摘要一致。M21最终脚本v3离线核验 `ok:true`，84份归档运行文件与当前源码一致、M9四冻结文件一致、原运行通过。文档变更未触发新的功能回归或云模型实验，不扩展原验收范围。

| 文档 | 用途 | 适用范围 |
|---|---|---|
| [.github/pull_request_template.md](../../.github/pull_request_template.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [AgentGuard v0.1 开发设计文档.md](../../AgentGuard%20v0.1%20%E5%BC%80%E5%8F%91%E8%AE%BE%E8%AE%A1%E6%96%87%E6%A1%A3.md) | 历史设计/计划 | 保留旧方案，不能作为自动执行指令或当前完成清单 |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [README.md](../../README.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [SECURITY.md](../../SECURITY.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [competition/docs/CODEX_IMPLEMENTATION_INSTRUCTIONS.md](../../competition/docs/CODEX_IMPLEMENTATION_INSTRUCTIONS.md) | 历史设计/计划 | 保留旧方案，不能作为自动执行指令或当前完成清单 |
| [competition/docs/SUJIE_FINAL_DESIGN.md](../../competition/docs/SUJIE_FINAL_DESIGN.md) | 历史设计/计划 | 保留旧方案，不能作为自动执行指令或当前完成清单 |
| [competition/docs/SUJIE_REVIEW_AND_PLAN_F2.md](../../competition/docs/SUJIE_REVIEW_AND_PLAN_F2.md) | 历史设计/计划 | 保留旧方案，不能作为自动执行指令或当前完成清单 |
| [competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md](../../competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md) | 当前规划 | 目标/排期非成绩；现状看状态表，四业务后已停止 |
| [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [docs/ROADMAP.md](../../docs/ROADMAP.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [docs/SECURITY_MODEL.md](../../docs/SECURITY_MODEL.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [docs/TEAM_COLLABORATION.md](../../docs/TEAM_COLLABORATION.md) | 历史设计/计划 | 保留旧方案，不能作为自动执行指令或当前完成清单 |
| [docs/THREAT_MODEL.md](../../docs/THREAT_MODEL.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/README.md](../README.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [sujie/console-vue/README.md](../console-vue/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/contracts/README.md](../contracts/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/control-plane-java/README.md](../control-plane-java/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/control-plane-python/README.md](../control-plane-python/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/demo-agent/README.md](../demo-agent/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/deploy/README.md](../deploy/README.md) | 历史M1复现 | 只验旧拓扑，新版整体隔离/可移植交付未验收 |
| [sujie/deploy/wheelhouse/README.md](../deploy/wheelhouse/README.md) | 历史M1复现 | 只验旧拓扑，新版整体隔离/可移植交付未验收 |
| [sujie/docs/COMPLETED_WORK_SUMMARY.md](COMPLETED_WORK_SUMMARY.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [sujie/docs/DEPENDENCIES.md](DEPENDENCIES.md) | 依赖说明 | 锁文件为准，环境/许可证/审计观察按原阶段解释 |
| [sujie/docs/DOCUMENT_INDEX.md](DOCUMENT_INDEX.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [sujie/docs/F2_IMPLEMENTATION_STATUS.md](F2_IMPLEMENTATION_STATUS.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [sujie/docs/M0_ACCEPTANCE.md](M0_ACCEPTANCE.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M0_FILE_MANIFEST.md](M0_FILE_MANIFEST.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M0_SECURITY.md](M0_SECURITY.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M10_TASK_DRIFT_DEVELOPMENT.md](M10_TASK_DRIFT_DEVELOPMENT.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M11_CONTEXT_EGRESS.md](M11_CONTEXT_EGRESS.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M12_AUTONOMOUS_APPROVAL_AND_BUDGET.md](M12_AUTONOMOUS_APPROVAL_AND_BUDGET.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M13_SEQUENCE_AND_TEMPORAL_SOURCES.md](M13_SEQUENCE_AND_TEMPORAL_SOURCES.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M14_NETWORK_AND_WEB_WORKFLOW.md](M14_NETWORK_AND_WEB_WORKFLOW.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M15_STRUCTURED_EXECUTION_AND_ARTIFACT.md](M15_STRUCTURED_EXECUTION_AND_ARTIFACT.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M16_GIT_DELIVERY_AND_APPROVAL.md](M16_GIT_DELIVERY_AND_APPROVAL.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M17_ACTUAL_ANALYTICAL_AGENTS.md](M17_ACTUAL_ANALYTICAL_AGENTS.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M18_CROSS_SESSION_MEMORY.md](M18_CROSS_SESSION_MEMORY.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M19_COMMON_RUNTIME_AND_BASELINES.md](M19_COMMON_RUNTIME_AND_BASELINES.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M1_1_SECURITY_HARDENING.md](M1_1_SECURITY_HARDENING.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M1_2_PURPOSE_PROVENANCE.md](M1_2_PURPOSE_PROVENANCE.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M1_ACCEPTANCE.md](M1_ACCEPTANCE.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M1_PROGRESS.md](M1_PROGRESS.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M20_VERIFIED_EVIDENCE_QUOTATIONS.md](M20_VERIFIED_EVIDENCE_QUOTATIONS.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M21_FOUR_BUSINESS_WORKFLOWS.md](M21_FOUR_BUSINESS_WORKFLOWS.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M2_PROGRESS.md](M2_PROGRESS.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M4_PROVENANCE_ABLATION.md](M4_PROVENANCE_ABLATION.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M4_REAL_MODEL.md](M4_REAL_MODEL.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M5_EXTERNAL_BENCHMARK.md](M5_EXTERNAL_BENCHMARK.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M5_INJECAGENT.md](M5_INJECAGENT.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M5_INJECAGENT_LOCAL.md](M5_INJECAGENT_LOCAL.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M6_OPERATOR_CONSOLE.md](M6_OPERATOR_CONSOLE.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M7_GATEWAY_PERFORMANCE.md](M7_GATEWAY_PERFORMANCE.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M8_AUTONOMOUS_CONSOLE.md](M8_AUTONOMOUS_CONSOLE.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/M9_FROZEN_CLASSIFICATION.md](M9_FROZEN_CLASSIFICATION.md) | 阶段记录 | 原阶段版本；顶部交接说明列明后续补齐与仍存边界 |
| [sujie/docs/PLAN_STATUS.md](PLAN_STATUS.md) | 历史设计/计划 | 保留旧方案，不能作为自动执行指令或当前完成清单 |
| [sujie/docs/PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [sujie/docs/TOPIC5_EVIDENCE_MATRIX.md](TOPIC5_EVIDENCE_MATRIX.md) | 当前入口/状态 | 截至M21；实现、证据与待办按本轮交接解释 |
| [sujie/docs/adr/ADR-001-dsl-lt.md](adr/ADR-001-dsl-lt.md) | 已接受决策 | 维持in操作符与契约包0.2/载荷1.0的决定 |
| [sujie/docs/adr/ADR-002-context-audit.md](adr/ADR-002-context-audit.md) | 已接受决策 | 维持in操作符与契约包0.2/载荷1.0的决定 |
| [sujie/eval/attacks/README.md](../eval/attacks/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/eval/baselines/README.md](../eval/baselines/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/eval/cases/README.md](../eval/cases/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/eval/oracles/README.md](../eval/oracles/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/mcp-servers/evidence-server/README.md](../mcp-servers/evidence-server/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/mcp-servers/git-server/README.md](../mcp-servers/git-server/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/mcp-servers/malicious-variants/README.md](../mcp-servers/malicious-variants/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/mcp-servers/memory-server/README.md](../mcp-servers/memory-server/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/mcp-servers/operations-server/README.md](../mcp-servers/operations-server/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
| [sujie/sandbox/README.md](../sandbox/README.md) | 当前模块/协作说明 | 含接口职责、兼容旧路径与当前限制；详见交接手册 |
