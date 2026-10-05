# M1 执行边界修复记录

日期：2026-10-05。分支：`fix/m1-authorization-boundaries`。修复依据：[首轮分析](../../docs/PROJECT_REVIEW_2026-10-05.md)中 F1–F6。

本轮修复 M1 已复现的授权与路径问题，并覆盖异步工具发现、并发预算和审批等待的失效路径。冻结的 9 类 Schema、三态语义、部署信任边界与依赖均未改变。结果是确定性工程验证，不是真实 LLM 防御指标。

## 本轮结果

- 完成：静态链接路径拒绝、授权有效期与关系校验、调用/网络预算、外发硬禁止、调用参数快照、执行前复核、审批快照与失败分支。
- 未完成：M2 来源传播、M3 工具扩展、M4 完整检测与安全重规划、M5 控制面、M6 真实模型评测。
- 架构是否变化：否；没有扩大 Agent 权限或引入新的可信服务。

## 文件

新增：

- `tests/test_m1_boundaries.py`：30 项真实 MCP 边界回归，包含正常路径对照。
- `docs/M1_HARDENING_2026-10-05.md`：本记录。
- `docs/M2_IMPLEMENTATION_PLAN.md`：下一阶段方案和验收矩阵，尚未实施。

修改：

- `gateway-python/src/sujie_gateway/m1_runtime.py`：授权/预算/审批与工具派发前复核。
- `mcp-servers/operations-server/server.py`：按原路径逐个检查链接组件。
- `demo-agent/sujie_demo_agent/graph.py`：证据读取失败时结束流程。
- `demo-agent/run_demo.py`、`tests/test_m1_e2e.py`：ASK 对照任务显式许可非秘密传输，补齐目标与网络预算。
- `gateway-python/tests/test_m1_policy.py`：纯策略测试使用固定 UTC 时钟，显式配置允许的传输场景。
- 根目录及主线 README、`docs/M1_PROGRESS.md`：链接本轮修复与后续方案。

## 修复行为

### 文件路径

对 Operations 工具的路径逐组件检查符号链接和 Windows junction，再执行规范化与工作区边界校验。末端链接、目录链接、悬空链接和指向工作区外的链接均不执行文件操作。普通嵌套报告路径继续允许读写。

文件操作仍在受控工具进程中校验链接，因此被拒绝的链接调用可以得到 `decision=ALLOW, ok=false, code=TOOL_EXECUTION_FAILED`：策略先允许逻辑资源，执行器拒绝实际路径；这不表示副作用已发生。测试直接检查秘密未返回、原文件未修改、悬空目标未创建。

本次处理静态链接，不声明抵御同容器恶意进程在检查后交换路径的 TOCTOU，也不把以文件名识别的秘密规则表述为完整敏感数据分类。

### 有效期与关系

每次策略决策检查 Contract/Grant 的 ACTIVE 状态和 UTC 有效期，以及动作主体、Grant ID、Grant 所属 Contract 与当前 Contract 的关系。到期时间恰好达到当前时刻即失效。

Proxy 完成异步工具注册复查后、实际派发前，再调用同步执行守卫。即使发现工具期间授权过期或被撤销，也不会继续写文件。

### 预算口径

本轮采用冻结设计中执行权限预算的保守实现：

| 场景 | `tool_calls` | `network_calls` |
|---|---:|---:|
| BLOCK、无效动作、工具版本检查失败 | 不消费 | 不消费 |
| ASK 提议与批准但尚未提交 | 不消费 | 不消费 |
| 实际派发文件读写工具 | 消费 1 | 不消费 |
| 实际派发传输工具 | 消费 1 | 消费 1 |
| 已派发但工具失败或结果未知 | 保留已消费额度 | 保留已消费额度 |
| 已提交审批的缓存重放 | 不再次消费 | 不再次消费 |

Contract 和 Grant 的预算分别校验、分别记录，以各自 ID 为键；二者都必须足够。缺少某维度视为该维度没有额度。预算检查与消费在同一 Gateway 的事件循环中同步完成，期间没有 await，从而防止并发调用重复使用最后一个额度。

ASK 不预占额度，多个等待审批的动作可能争用剩余额度；最终在实际派发前重新判断。额度消耗后，尚未执行的审批无法继续提交。

预算是单 Gateway 实例内存状态；不提供多个实例共享同一 Contract 的全局配额，也不提供崩溃后的预算恢复。M3 的子 Agent 和 M5 的多任务服务接入须显式复用或扩展可信账本。

### 外发与审批

`external.data_transfer` 禁止项匹配 `data.transfer` 到外部目的地的动作；`data.transfer` 禁止项限制所有此类传输。网络资源同样必须在 Grant 目标范围内。

ASK 演示使用独立可信测试合同，明确移除外发禁止项、加入许可目标和网络额度；默认告警任务仍禁止外发。这是修正对照配置，未让普通用户审批覆盖硬禁止。

请求审批时保存原始绑定快照；批准时如果合同等绑定内容已变化，返回 `APPROVAL_STALE`，不自动绑定到新任务版本。提交前和异步发现工具后再次校验审批有效期及绑定，后者失效时缓存拒绝结果，重放不再执行。

普通调用也执行自有的 JSON 参数副本，避免调用方在 await 期间把已授权报告路径改为秘密文件路径。

### Agent 失败分支

真实 Evidence MCP 读取不存在的告警时，Agent 输出 `completed=false` 并结束；不会进入依赖缺失 `alert` 字段的动作节点，也不会写出伪报告。

## 验收用例

| 测试 ID | 关键条件与真实 Oracle |
|---|---|
| M1-BOUNDARY-001 | 合同/Grant 过期、零额度、外来 Grant：无文件创建、秘密保持原值 |
| M1-BOUNDARY-002 | 5 个并发写提议仅 1 个额度：只有 1 个报告文件 |
| M1-BOUNDARY-003 | 被阻断读秘密后仍能用剩余额度写报告 |
| M1-BOUNDARY-004 | 文件读取工具实际失败后，额度仍消耗，后续无写文件 |
| M1-BOUNDARY-005 | 两种传输禁止项：无审批、无真实 HTTP POST |
| M1-BOUNDARY-006 | Contract/Grant 零网络额度或缺失维度：无 POST |
| M1-BOUNDARY-007 | Grant 未包含许可网络目标：无 POST |
| M1-BOUNDARY-008 | 两个已批准 ASK 共享最后的工具/网络额度：只有一次 POST，重放不再发送 |
| M1-BOUNDARY-009 | 工具发现期间过期/撤销：无报告写入 |
| M1-BOUNDARY-010 | await 期间调用方改变参数：原报告写成，秘密保持原值 |
| M1-BOUNDARY-011 | 五类链接路径：秘密不返回、不修改；悬空目标不创建 |
| M1-BOUNDARY-012 | 正常嵌套路径可真实写入并读回 |
| M1-BOUNDARY-013 | 真实 Evidence 读取失败：任务失败结束，无报告 |
| M1-BOUNDARY-014 | 提议后、批准前合同版本变化：不重新绑定批准，无 POST |
| M1-BOUNDARY-015 | 工具发现期间审批过期或绑定漂移：无 POST，重复 commit 仍无 POST |

## 验证

环境：macOS、Python 3.12.15、65 个锁定依赖。

```bash
cd /Users/lijiapeng/Documents/project_all/AgentGuard/sujie
.venv/bin/python dev.py check
.venv/bin/python dev.py demo
uv pip check --python .venv/bin/python
```

实际结果：

- Ruff check 通过、25 个 Python 文件格式检查通过。
- 全套测试 202 passed、0 failed，耗时 35.43 秒；新增 30 项回归。
- 1 条 Starlette/AnyIO 弃用警告，与修复前相同。
- 演示退出码 0：正常任务 ALLOW/ALLOW；注入任务 ALLOW/BLOCK/BLOCK/ALLOW；两者均写成报告，Receiver 请求数均为 0。
- ASK 演示：批准前不执行、批准后两次并发提交只有一次真实非秘密 HTTP POST。
- 依赖检查通过，无新依赖。
- Git diff 空白检查通过。

未运行：Windows CI、Docker/Ubuntu 容器隔离复验、真实 LLM、性能基准和外部基准。本机未发现 Docker CLI；没有修改 Compose 或容器网络。Windows 无创建符号链接权限时链接测试会显式 skip，不能按通过统计。

首次新增测试使用异步 yield fixture 管理 MCP，触发 AnyIO 跨任务退出错误；已改为在同一测试协程中进入/退出异步上下文。上述最终结果包含正常清理，不把此前的 teardown 错误计入通过结果。

202 是自动化测试总数，包含 Schema 参数化测试，不能当作“200 条攻击回归”或真实模型防御成绩。

## 安全影响与残余风险

- 新增信任边界：无。
- 新增外部依赖：无。
- 持久化幂等、预算恢复、多副本一致性、完整来源传播、敏感内容分类和容器内部 TOCTOU 仍未覆盖。
- 实际策略 YAML 与合同示例 `policy_snapshot_hash` 的绑定、可查询证据存储、完整 DAG 等仍需后续实现。
- 提交后的不可撤回远程效果不提供通用回滚；本轮只检查派发前授权与进程内重放。

## 下一步

下一里程碑方案见 [M2_IMPLEMENTATION_PLAN.md](M2_IMPLEMENTATION_PLAN.md)。M2 先落实可信来源登记和传播，再将其接入真实出口与审批绑定，最后提供脱敏 DAG 查询。本文不宣称 M2 已实施。
