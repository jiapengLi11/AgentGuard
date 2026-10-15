# M0 交付与验收记录

> **2026-10-15 交接说明：** 历史M0纯领域验收。当前已推进到M21；九类对象仍在，契约包已升0.2、载荷版本仍1.0。原测试数/文件和“下一步”只属于M0，不是当前安装步骤或完成总量。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

日期：2026-09-05
架构基线：SUJIE_FINAL_DESIGN.md F1.0
状态：M0 代码与本机测试完成，待用户验收；未进入 M1。

## 本轮结果

完成：Monorepo 骨架、九类 Schema、18 份合法/非法 fixtures、共享枚举与冻结摘要、
九类不可变领域快照、六组架构守卫、开发命令、环境示例、占位 Compose、
Linux/Windows CI 配置、依赖/边界/ADR 文档。
架构没有更换；最终设计与实施指令原文未改。
DSL 的 lt 冲突见 ADR-001，相关实现未开始。

## 文件

新增：sujie/ 中源码、Schema、测试、模块占位和文档，以及根目录 CI。
修改：根 README 入口与 .gitignore；未修改历史 agentguard/、tests/、benchmark/。
本机创建隔离虚拟环境 sujie/.venv，已排除版本控制。
逐项文件列表见 M0_FILE_MANIFEST.md。

## Schema 清单

1. task-contract.schema.json
2. task-grant.schema.json
3. provenance-envelope.schema.json
4. semantic-action.schema.json
5. decision-record.schema.json
6. approval-record.schema.json
7. trace-event.schema.json
8. security-exception.schema.json
9. detection-finding.schema.json

每份 Schema 的根和嵌套对象均禁止未知字段；有 schema_version、必填项及类型/格式/枚举。
包版本 0.1 与载荷版本 1.0 的区别见 contracts/README.md。

## 不变量清单

- 子 Grant 不超出父 Grant：效果、规范资源范围、期限、预算维度和额度。
- DATA_ONLY 不能作为 AUTHORIZE 来源，伪造 allowed_uses 也不能绕过。
- 普通转换不能提高 integrity/authority，禁止错误声称摘要有精确来源映射。
- 派生物保守继承机密性和用途；不得丢失父集合或禁止用途。
- BLOCK / HARD_BLOCK 不被普通审批或模型建议放行。
- 工具、参数、内容、来源、任务和策略 Hash 变化使旧审批绑定失效。

正向对照：合法权限收窄、危险证据 READ/ANALYZE/QUOTE/STORE_EVIDENCE、
合法派生、有效 ASK 确认均能通过。不是全部拒绝。

## 验证

工作目录为仓库根目录，使用本项目 Python 3.12.14 虚拟环境。

~~~powershell
.\sujie\.venv\Scripts\python.exe sujie/dev.py check
.\sujie\.venv\Scripts\python.exe sujie/dev.py schema
.\sujie\.venv\Scripts\python.exe sujie/dev.py unit
.\sujie\.venv\Scripts\python.exe -m pip check
.\sujie\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

实际结果：
- check：Ruff 静态/格式检查通过；158 项测试通过，0 失败。
- schema：89 项通过，0 失败。
- unit：69 项领域守卫与工程测试通过，0 失败。
- pip check：No broken requirements found。
- 历史原型 unittest：8 项通过，0 失败（单独计数）。
- 首轮出现 4 项 URI 格式检查失败；补齐依赖后保持原用例复测通过。

未运行：
- Docker Compose 官方配置验证/启动、Linux 容器隔离：本机未发现 Docker。
  已完成 YAML 静态断言；CI 设置了 Compose config 检查，但未在远端运行。
- GitHub Actions：目录不是 Git 仓库，本轮没有初始化 Git、创建远端或推送。
- 真实模型/MCP、端到端任务、性能与攻防指标：不属于 M0。
- Java 21 / Spring Boot / Vue 构建：本轮只有占位，未构建。

158 项是参数化测试展开后的测试项数量，不是 158 个独立攻击案例，
不替代 P0 的 200 条安全回归或 60 个真实基础任务。

## 安全影响

新增真实服务信任边界：无。没有启动网络服务、读取真实秘密或授予 Agent 工具。
新增依赖仅在隔离 venv，用途/许可证/替代方案见 DEPENDENCIES.md。
M0 的 Schema 校验不是认证；审批函数不是原子消费；路径检查不是 OS 安全边界。
详见 M0_SECURITY.md。

## 下一步

用户验收后进入 M1：真实 LangGraph Agent + 两个 MCP Server + 不可绕过的代理/执行器，
完成 clean / indirect-injection 两条真实副作用验证。
先确认 ADR-001 的 DSL 操作符冲突。本轮停止，不擅自进入 M1。
