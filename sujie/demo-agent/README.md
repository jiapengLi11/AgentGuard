# Agent Host 与演示

更新：2026-10-15。当前目录同时保留确定性LangGraph测试图和实际百炼有界Host。

| 文件 | 职责 |
|---|---|
| `sujie_demo_agent/graph.py` | 早期确定性决策模型及适配接口；不是云模型成绩 |
| `sujie_demo_agent/bailian_agent.py` | Provider和受控工具调用Host，按profile暴露工具，实际调用Gateway |
| `protected_model.py` / `model_budget.py` / `tokenizer_mapper.py`（同包） | 请求/回应保护、角色共享预算、本地token映射 |
| `delegated_agent.py` | main→review→verify实际对话、Grant收窄与来源交接；同Host |
| `evidence_analysis.py` | report可选有界无工具分析，Host核对字面引用，不验证语义标签 |
| `business_workflows.py` | 四业务合成输入/可信规则与时间线查询计算；不把Oracle gold交给模型 |
| `semantic_detector.py` / `semantic_detector_v2.py` | M9冻结分类实现 / M10开发候选；不是新正式留出成绩 |

从 `sujie/` 运行 `.\.venv\Scripts\python.exe dev.py demo`，执行真实MCP的正常/注入/ASK演示，明确为非LLM。当前控制台云模型启动、13profile及限额见[交接手册](../docs/PROJECT_HANDOFF.md)，不再只限旧四工具或单报告循环。

工具提议、检测建议和子角色输出不能授权；BLOCK后有界恢复不增加权限。Provider凭据不进入工具环境或模型消息。模型API亦是出口，已有保护不等于全仓库历史入口/完整有效请求均已覆盖。M9四文件冻结，改进另建版本。F3剩余工作未因本轮文档更新恢复。
