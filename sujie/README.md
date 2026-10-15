# 溯界比赛实现

更新：2026-10-15，代码截至M21及协议索引修正。当前运行/评测主线是本目录。

## 交接入口

- [已完成工作简明汇总](docs/COMPLETED_WORK_SUMMARY.md)
- [项目交接手册](docs/PROJECT_HANDOFF.md)：安装、启动、预算、代码定位、证据和剩余工作
- [文档索引](docs/DOCUMENT_INDEX.md)：当前指南与历史记录
- [当前工作包](docs/F2_IMPLEMENTATION_STATUS.md) / [赛题证据矩阵](docs/TOPIC5_EVIDENCE_MATRIX.md)

已完成契约/三态网关、真实MCP、来源传播、模型输入/出口保护、共享预算、IOC/Git自主审批、网络/进程/Git效果、多层Agent、两个Memory会话、字面引用核验及四类新业务，共13个开发profile。Python控制面与Vue已实现，Java/MySQL未实现。

**四类业务按用户要求完成后停止；F3整体未完成。本轮仅更新交接文档。**

## 安装与本机启动

在本目录，Python3.12、Node20.19+或22.12+，Git业务另需Git：

```powershell
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

Linux/macOS用 `.venv/bin/python`。默认地址 `http://127.0.0.1:8765`，凭据为本机 `.control-runtime/operator-token.txt`。无云凭据时使用固定动作/确定性演示；安装及首次固定分词器准备需要网络或核验离线资源，分词器不含模型权重。

云模型/端口/预算参数用 `control-plane-python/run_console.py`，见[手册](docs/PROJECT_HANDOFF.md)。`dev.py console`不透传参数，`.env.example`不是实际Provider配置。旧8765进程未随代码自动更新，勿清理用户任务；先导出再协调重启或使用新端口。

## 模块

| 目录 | 职责 |
|---|---|
| `contracts/` | 九类Schema、包0.2/载荷1.0、fixtures与不变量 |
| `gateway-python/` | MCP代理、合同/Grant、DSL、三态/审批、来源/Trace与序列 |
| `demo-agent/` | 旧LangGraph演示、有界百炼Host、子角色、正文分析、模型保护与预算 |
| `control-plane-python/` | 独立认证服务、13profile、临时环境及事实/读取/效果Oracle |
| `console-vue/` | 同源操作者页面；前端不是授权来源 |
| `mcp-servers/`、`sandbox/` | 文件、网络、执行、Git交付、版本Memory及旧测试服务/实际封闭副作用 |
| `eval/` | 冻结协议、开发数据、五配置、校准、云实验和离线重算 |
| `deploy/` | 历史M1拓扑及离线说明；新版整体隔离未验收 |
| `control-plane-java/` | 未实现占位，不是启动依赖 |

## 验证与边界

`python dev.py check`执行ruff/格式检查和pytest；`demo`为非LLM确定性真实MCP演示。`schema / unit / test / lint / format`为开发入口，`format`会修改代码。评测/性能脚本会写输出，复现时选择新目录，不覆盖旧成绩。

M21脚本16/16业务完成；云首轮3/4、修复时间线单独完成，合计18请求/29,789tokens，跨版本不合并成功率。修复前完整479 passed/2 skipped/1 warning；修复后52专项通过，静态/格式及Vue构建通过。[M21记录](docs/M21_FOUR_BUSINESS_WORKFLOWS.md)保留版本边界，不能表述为修复后同版全量验收、正式ASR或排名。

Host与执行器可信；子/孙对话同Host；任务/审批临时，预算账本持久不等于任务恢复；审批单次提交不等于跨崩溃exactly-once。本地token不是云内部token，来源Hash不是事实证明，字面引用核验不是语义核实。

正式独立任务/C-A-Q-R五配置比较、全入口/有效请求绑定、覆盖矩阵、信息保全/恢复比较、新版Linux隔离性能和材料仍待完成。旧原型不参加主评测，历史M1容器/性能/分类/云报告按各自版本解释。接手需另存忽略的证据、源码归档及固定资源；凭据私下交接。
