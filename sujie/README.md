# 溯界（Sujie）

大模型智能体运行时安全网关平台。
可信任务契约冻结权限，来源—用途信封约束传播，效果级闸门实施 ALLOW / ASK / BLOCK。

唯一架构基线：[SUJIE_FINAL_DESIGN.md](../competition/docs/SUJIE_FINAL_DESIGN.md)。
实施顺序：[CODEX_IMPLEMENTATION_INSTRUCTIONS.md](../competition/docs/CODEX_IMPLEMENTATION_INSTRUCTIONS.md)。

## 当前完成状态

M0、M1 已验收。当前完成两个真实 stdio MCP Server、MCP Proxy、LangGraph
工作流、file.read/file.write/data.transfer 效果映射、最小 DSL、三态决策、内存 Trace
和封闭接收端 Oracle；ASK 已具备动作绑定、可信审批和进程内原子单次提交，本机确定性闭环已通过。
并已在 Ubuntu VM 通过双内部网络的容器不可绕过验收。详见
[M1 验收记录](docs/M1_ACCEPTANCE.md)与 [M1 进度记录](docs/M1_PROGRESS.md)。

尚未运行真实 LLM，因此没有比赛 ASR 成绩。
Spring Boot、Vue、来源传播及其他工具仍未实现。历史 AgentGuard 代码未复用为安全内核。

2026-10-05 补充修复授权有效期、预算、Grant 归属、静态链接路径、外发禁止和失败分支；本机检查 202 项测试通过。见 [M1 修复记录](docs/M1_HARDENING_2026-10-05.md)和 [M2 实施方案](docs/M2_IMPLEMENTATION_PLAN.md)。

## 模块

| 目录 | 目标职责 | 当前状态 |
|---|---|---|
| contracts | 九类 JSON Schema、共享枚举、fixtures 和测试 | 已实现 |
| gateway-python | Python 3.12 数据面 | M1 stdio 代理、效果映射、DSL、三态与 Trace |
| control-plane-java | Java 21 / Spring Boot 3 / MySQL 8 控制面 | 占位 |
| console-vue | Vue 3 / TypeScript 控制台 | 占位 |
| demo-agent | LangGraph 受控 Agent | 可替换决策模型；确定性测试模型已验证 |
| mcp-servers | Evidence、Operations 与恶意变体 | 两个真实 stdio Server；恶意变体待后续 |
| sandbox | 隔离执行器、本地接收端和 Git 远端 | 真实本地接收端与容器 Oracle；Git 待后续 |
| eval | 真实任务、攻击、Oracle、结果 | 两条确定性闭环 + 接收端校准；无 LLM 成绩 |
| deploy | Compose 部署 | M1 四容器、双内部网络已在 Ubuntu VM 验收 |

## 快速验证

交付雏形：`python dev.py deliver` 运行真实 M1 演示，生成离线回放、验收 JSON、事件元数据和 SHA-256 ZIP 包。`python dev.py verify-delivery --output <目录>` 校验解压后的交付结果。该回放不包含交互审批或 M2 来源 DAG；运行与队友接力说明见 [DELIVERY_PROTOTYPE.md](docs/DELIVERY_PROTOTYPE.md)。

在本目录使用 Python 3.12：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe dev.py check
~~~

Linux/macOS 将解释器改为 .venv/bin/python。
统一命令：dev.py schema / unit / test / lint / format / check。
check 运行静态检查、格式检查、Schema 与 Python 单元测试。

确定性真实协议演示：.\.venv\Scripts\python.exe dev.py demo。
输出覆盖正常、间接注入和 ASK 审批单次提交，并明确标记
deterministic-test-model-not-llm；独立 API、交互式界面和真实模型待完成。
M1 容器验证：`sh deploy/run_m1_container_test.sh`。VM 无外网时按
[部署说明](deploy/README.md)准备基础镜像和 wheelhouse；成功输出与证据见
[M1 验收记录](docs/M1_ACCEPTANCE.md)。`deploy/compose.yaml` 仅保留为 M0 历史占位，
不得用于证明隔离或安全闭环。

## 契约和边界

Schema 包版本为 0.1；载荷 schema_version 保留最终设计示例的 1.0。
九类业务对象均有封闭字段、必填项、格式/枚举和合法/非法 fixture。
格式断言显式启用；ULID / UUIDv7、UTC 日期、Hash 都会验证。
见 [契约说明](contracts/README.md)、[M0 安全边界](docs/M0_SECURITY.md)。

Schema 校验不等于认证、授权、可信签名或真实工具安全。
当前容器闭环只证明 M1 定义的 Agent 隔离边界；可信审批入口尚未独立成控制面服务，
Gateway 自身失陷、持久化幂等及来源传播仍不在该结论内。

## 待确认事项

[ADR-001](docs/adr/ADR-001-dsl-lt.md) 已按用户授权接受方案 B：DSL 使用 in，
不为目的地等级引入隐含字符串顺序。

依赖、许可证与替代方案见 [DEPENDENCIES.md](docs/DEPENDENCIES.md)。
