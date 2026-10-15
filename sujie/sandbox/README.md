# 封闭执行器与副作用 Oracle

更新：2026-10-15。此目录用于合成靶场，当前范围超出M1 Receiver：

| 文件 | 当前职责 |
|---|---|
| `receiver.py` / `receiver_service.py` | 本地HTTP接收及实际请求/合成蜜标观察 |
| `web_fixture.py` / `network_executor.py` | 封闭网页与有界GET/POST，目标/请求/重定向检查 |
| `execution_executor.py` / `sujie-inspect.py` | 注册程序/argv、内容摘要、实际子进程与结构化收据 |
| `sealed_git.py` | 临时源/裸远端、确切对象/ref、状态与lease校验 |
| `versioned_memory.py` | 固定策略/键、SQLite版本原文、摘要/CAS追加与读取一致性 |
| `container_oracle.py` | 历史M1容器网络/挂载及结果检查 |

详细证据见[M14](../docs/M14_NETWORK_AND_WEB_WORKFLOW.md)、[M15](../docs/M15_STRUCTURED_EXECUTION_AND_ARTIFACT.md)、[M16](../docs/M16_GIT_DELIVERY_AND_APPROVAL.md)、[M18](../docs/M18_CROSS_SESSION_MEMORY.md)。Host另以事实/实际读取/报告Oracle判定业务，不以Receiver为空替代任务完成。

M1曾完成Linux容器验收，但当前完整Host/工具/子Agent拓扑没有新版Linux验收；有真实子进程不等于通用OS沙箱。不要把这些执行器接到任意生产路径/公网写入后继续引用封闭测试结论。交接与环境缺口见[手册](../docs/PROJECT_HANDOFF.md)。
