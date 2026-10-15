# M7：真实 MCP 网关开销与 SQLite 配置对照

> **2026-10-15 交接说明：** 历史特定读取负载的MCP/网关/SQLite性能实验，保留原环境、版本及P95/P99。新增模型/子Agent/Memory/工具未在同一新版拓扑验全；不能将旧P95当作当前端到端性能或已达F3目标。旧固定输出命令重跑可能覆盖文件，接手选新输出。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

## 测量内容

此前 `bench_policy.py` 只测内存策略判断。本次新增 `eval/bench_gateway.py`，测量
同一真实 stdio MCP 读取在直连、完整内存 Trace、持久化 Trace 路径中的端到端耗时，
并测私密读取在工具执行前的阻断耗时。原始纳秒样本、轮次、实际工具调用计数和
SQLite 配置均写入报告，供重算分位数。

同一进程、同一 MCP 连接、同一 63-byte 合成告警，每轮预热 10 次、正式测量
100 次，共 3 轮。每个采样点轮换直连、内存、新 SQLite、旧 SQLite 的顺序，
之后执行一次阻断探针。每轮建立新网关，轮内保留全部 Trace 和已暴露 Artifact。
模型、操作者 HTTP、MCP 启动/注册均不在计时内，没有云 API 调用。

```powershell
.\.venv\Scripts\python.exe eval/bench_gateway.py --samples 100 --repeats 3 `
  --out eval/reports/runs/gateway_latency_paired_v3.json
```

`dev.py bench-gateway` 使用相同默认参数，输出到 `gateway_latency.json`。

## 发现与修改

初步测量显示持久化 Trace 的事务提交占主要额外开销。逐条事件、Artifact 和
规范化视图仍即时提交；日志方式改为 `TRUNCATE`，显式设置 `synchronous=EXTRA`，
启动时核验设置，失败即拒绝初始化。

TRUNCATE 通过将回滚日志截断至零提交，可减少删除文件涉及的目录操作；EXTRA
是回滚日志的持久性设置。这些行为依据
[SQLite 官方 PRAGMA 文档](https://www.sqlite.org/pragma.html#pragma_journal_mode)。
没有引入异步证据缓冲或降低同步设置。

本机 SQLite 为 3.43.1。检查官方文档后未选用 WAL：该版本早于 WAL-reset 修复版本，
且未来多连接写入/检查点设计需要单独验证。具体受影响版本和条件见
[SQLite WAL 文档](https://www.sqlite.org/wal.html#the_wal_reset_bug)。

## 同场对照结果

原始报告：`eval/reports/runs/gateway_latency_paired_v3.json`，运行产物已忽略。
Windows 11、Python 3.12.2、SQLite 3.43.1。本次以同场报告作为对照依据；
早期 `gateway_latency_v1/v2.json` 是探索记录，部分与测试运行时间重叠，不用于最终提升比例。

| 路径 | 样本 | P50 ms | P95 ms | P99 ms |
|---|---:|---:|---:|---:|
| 直连 MCP 读取 | 300 | 4.148 | 4.655 | 5.082 |
| 完整网关，内存 Trace | 300 | 7.206 | 8.222 | 8.853 |
| 原 SQLite DELETE/FULL | 300 | 28.766 | 30.955 | 35.228 |
| 当前 SQLite TRUNCATE/EXTRA | 300 | 22.919 | 25.149 | 39.744 |
| 执行前阻断私密读取 | 300 | 2.325 | 3.053 | 3.350 |

当前 SQLite 路径 P95 相比旧配置下降 **18.75%**；296/300 对采样中新配置更快。
逐对旧减新耗时差的 P50 为 5.771 ms。这是本机这个读取负载下的观察，P99
本轮上升，不能声称尾延迟全面改善，也不能推广为所有工具的固定性能提升。

每轮两个持久化网关均记录 110 个 Artifact、665 个事件，数据库完整性检查均为
`ok`。设置实际查询分别为 `delete / synchronous=2` 和 `truncate / synchronous=3`。
共 1,320 次 Evidence 实际 MCP 调用（含预热和四条读取路径），私密读取工具的
实际调用计数为 0。阻断路径没有通过减少日志或跳过授权获得低延迟。

Trace 单测验证当前同步配置、持久化、关闭后重新打开与完整性；控制台集成测试
仍核对审批单次执行、拒绝、来源和实际 HTTP 副作用。设置检查与完整性检查
不等于实测断电、磁盘损坏或跨进程事务恢复。

## 尚未完成的测量

只有一个固定大小的正常读取操作，无并发；小数据、高 I/O 成本会放大日志方式差异。
正常任务带入的来源历史在轮内增长，报告提供每轮前后 20 样本的 P50；不能把
空历史表现作为长会话上界。读取之外的写文件、外发、审批提交、Memory、Git、
exec，以及云模型延迟和语义调用比例仍需要独立负载。后续应包括不同内容大小、
攻击文本、长会话、并发及部署环境；不以本机固定数值作为 CI 性能门槛。
