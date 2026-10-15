# Python 操作者控制面

更新：2026-10-15，当前比赛运行入口。独立FastAPI应用，复用Gateway授权/审批/Trace；Agent API不挂载操作者审批路由。

完整安装/云配置/预算/证据保存见[交接手册](../docs/PROJECT_HANDOFF.md)。从 `sujie/` 构建前端后运行：

```powershell
.\.venv\Scripts\python.exe dev.py console
```

默认仅监听 `127.0.0.1:8765`，登录凭据为 `.control-runtime/operator-token.txt`。云模型或端口等参数必须直接运行：

```powershell
.\.venv\Scripts\python.exe control-plane-python/run_console.py --port 8767 --credentials-file 'C:\private\bailian-credentials.csv'
```

此处为占位路径；CSV私密交接，不上传页面/MCP/模型消息。`dev.py console`不转发参数，`.env.example`不提供实际配置。非默认端口凭据为 `operator-token-8767.txt`。旧进程不自动加载新代码，先导出用户任务再协调升级。

## 当前能力

13个开发profile及适用场景见手册；其中M21的时间线、Issue、附件、知识冲突支持 `quoted`，其他profile拒绝该场景。主入口为 `sujie_control/api.py`，模板/生命周期在 `profiles.py`、`runtime.py`、`model_runner.py`，业务判定在 `business_oracles.py`，时间线查询在 `timeline_query.py`。

IOC/Git模型可暂停→批准→提交→续跑；批准本身不执行。仅eval支持五配置切换，操作者HTTP不接受该开关。来源/DAG、完整记录提议序列、子Agent、Memory、业务读取/报告状态及脱敏导出均来自实际后端。

## 持久化与限制

单操作者、临时合成任务；关闭任务/服务会清理工作区，先导出。CLI共享模型预算默认SQLite持久化，任务/审批/提交去重不支持跨崩溃恢复。子/孙Agent同Host，新版整体容器隔离未验收。源码中的M1命名沿用至今，不意味着只支持早期链路。

[M12审批](../docs/M12_AUTONOMOUS_APPROVAL_AND_BUDGET.md) · [M16 Git](../docs/M16_GIT_DELIVERY_AND_APPROVAL.md) · [M17子Agent](../docs/M17_ACTUAL_ANALYTICAL_AGENTS.md) · [M18 Memory](../docs/M18_CROSS_SESSION_MEMORY.md) · [M20引用](../docs/M20_VERIFIED_EVIDENCE_QUOTATIONS.md) · [M21业务](../docs/M21_FOUR_BUSINESS_WORKFLOWS.md)
