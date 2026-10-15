# M6：操作者控制面与可演示证据闭环

> **2026-10-15 交接说明：** 历史两模板固定动作/旧界面验收。当前13profile及真实模型自主ASK/子孙/两会话/业务状态已接入；运行以交接手册为准。M6截图/窄屏结果不证明最新M21布局，后者仅类型检查/构建及HTTP集成验证。任务/审批仍临时，Java/MySQL未实现。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

## 本次计划调整

原设计包含 Java/Spring/MySQL 控制面和 Vue 控制台。Java 目录仍为空，本机没有
Java/Maven；Python Gateway 已经实现契约、效果授权、来源及动作绑定审批。
依据用户允许随效果调整计划的授权，本次先用独立 FastAPI 应用复用这个领域实现，
完成可验证的操作者闭环。Java 适配和持久化控制面延后，不作为已完成项。

## 已实现的功能

| 功能 | 具体行为与证据 |
|---|---|
| 身份与入口分离 | 操作者 Bearer 认证；本机随机凭据；独立应用与端口；Agent API 没有审批路由 |
| 任务创建 | 两个固定契约模板：本地报告、公开 IOC 审批外发；正常/注入两种合成证据；最多 8 个活跃任务 |
| 任务隔离 | 每任务独立临时工作区、SQLite Trace、MCP 子进程与 HTTP Receiver；MCP 开关由同一 asyncio worker 管理 |
| 工具路径 | 点击固定动作，实际调用 Evidence/Operations stdio MCP；展示 ALLOW、ASK、BLOCK 和接收端实际请求 |
| 审批闭环 | 展示目标、参数/输入/来源/策略 Hash、截止时间；批准、拒绝、提交；review_hash 绑定所审动作；提交仍由 Gateway 再核验 |
| Trace/来源 | 脱敏时序、检测元数据、父事件、Artifact DAG；点击来源查后继节点、关联事件和实际 RESOURCE_AFFECTED |
| 安全续做 | 生成本地固定事实报告；可信 IPv4 提取器保留父来源；提取结果仍需审批才能外发 |
| 证据导出 | JSON 包含冻结契约/Grant、脱敏事件、来源、审批指纹及 Oracle；导出摘要及图关联可离线复核 |
| 策略展示 | 展示当前实际 DSL 和快照 Hash，只读；没有策略发布接口 |

界面不显示原始证据正文、工具参数、Artifact 内容路径或蜜标。仅对与待审输入 Hash
一致的公开 IOC 提供明文预览。原始 Trace payload_hash 仍作为来源元数据保留；脱敏
导出不包含原始 payload，不能用展示字段重新计算原始 payload_hash。

凭据仅保存在 Vue 页面内存，刷新或退出后失效于该页面。服务采用同源静态资源，
没有 CORS 放行、远端 CDN 或浏览器持久凭据。返回 no-store、nosniff、CSP 和
DENY frame；检查 Host/Origin；32 KiB 请求体上限也覆盖分块请求。
MCP 子进程仅获得所需工作区/证据/接收端配置，未注入操作者凭据。

## 运行和演示

Python 3.12 venv 与 requirements.lock 已安装；前端要求 Node 20.19+ 或 22.12+。
在 `sujie`：

```powershell
Push-Location console-vue
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe dev.py console
```

打开 `http://127.0.0.1:8765`，粘贴 `.control-runtime/operator-token.txt` 内本次
启动的凭据。启动器不打印凭据，只输出文件位置，服务只绑定 loopback。
自定义端口可用 `python control-plane-python/run_console.py --port 8767`。

推荐演示顺序：

1. 选择“公开 IOC 审批外发”及“含提示注入”，创建任务。
2. 读取证据；尝试私密读取、原始外发，观察两个 BLOCK。
3. 生成本地报告，检查报告已落盘。
4. 提取公开 IOC；请求外发，得到 ASK。接收端请求仍为 0。
5. 在审批页核对目标和 IOC，批准再提交。检查接收端请求为 1、蜜标未泄漏。
6. 点原始来源，核对后继节点及报告/外发资源。
7. 导出脱敏证据，再关闭任务。关闭会清理临时文件。

离线复核下载文件：

```powershell
.\.venv\Scripts\python.exe eval/verify_operator_export.py <导出的JSON路径>
```

该工具检查导出摘要、来源 DAG 和事件关联。Hash 是完整性摘要，没有签名，
不能证明报告由特定可信主机生成，也不能证明比赛全量攻击成功率。

## 验证结果

本次接口和投影验证共 9 项通过，覆盖认证/恶意 Origin、分块大请求、跨任务审批、
硬阻断不可审批、参数篡改拒绝、先批准后单次执行、重复提交、拒绝已批准未提交动作、
Trace 脱敏、Hash 绑定、DAG 查询和清理。实际调用 stdio MCP 及本地 HTTP Receiver，
没有消耗百炼 API。

浏览器实测完整 IOC 路径的脱敏原始导出位于
`eval/reports/runs/operator_console_ui_v1.json`（忽略运行产物，不提交）。

| 指标 | 实际值 |
|---|---:|
| ALLOW / ASK / BLOCK 记录 | 2 / 1 / 2 |
| 检测发现 | 1 |
| 事件 / 来源节点 | 30 / 4 |
| 报告落盘 | 是 |
| 接收端实际 HTTP 请求 | 1 |
| 合成蜜标泄漏 | 否 |

导出 Hash：`sha256:42ace607e3d68ad2d02ad150fd379975c8466cd84d24823e5477ce3bcf14e6fa`。
来源查询返回报告资源及 `https://receiver.invalid/upload`；逻辑目标映射到 loopback
Receiver，未向公网外发。界面发现的转换对象标签问题已修复并在浏览器重新核对。

`npm ci`、`vue-tsc --noEmit` 和 Vite 构建成功，npm 查询返回 0 个已知漏洞。
CI 新增前端构建，远端 CI 尚未执行。Python 全量检查为 258 通过、2 跳过
（Windows 符号链接权限、POSIX API），另有现有 anyio 弃用警告。
390 px 窄视口已检查无文档级横向溢出；来源图可在卡片内横向滚动。

## 边界与下一步

本页记录 M6 的单操作者、临时任务、固定动作封闭演示。后续 M8 已接入
[受限自主报告循环](M8_AUTONOMOUS_CONSOLE.md)，IOC 外发仍用人工审批工作流。
固定动作演示不计模型攻击结果。
本机操作者服务仍是可信主机进程，不防同账户本地恶意进程读取凭据，不等于生产
身份认证或容器隔离验收。服务关闭后任务与审批状态不保留；进程内单次提交不等于
跨重启幂等。页面的明确关闭动作会清理工作区，证据应先导出。

后续优先扩展独立基础任务与可信工具 Schema、冻结未暴露留出集、完成必选基线及
消融重复实验；同时补网关延迟分离测量、策略发布和部署验收。持久化、多操作者、
Java/MySQL 适配按这些实际需求推进，不把技术栈数量作为成果指标。

框架文档核对：Context7 本次连接失败，采用官方
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)、
[Bearer 安全依赖](https://fastapi.tiangolo.com/reference/security/#fastapi.security.HTTPBearer)、
[静态文件](https://fastapi.tiangolo.com/tutorial/static-files/)、
[Vue TypeScript](https://vuejs.org/guide/typescript/overview.html)、
[Vite 入门](https://vite.dev/guide/)；版本来自 npm 官方注册表并在锁文件中固定。
