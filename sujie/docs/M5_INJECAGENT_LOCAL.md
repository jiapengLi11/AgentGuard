# InjecAgent 选定任务的本地执行映射

> **2026-10-15 交接说明：** 历史三个上游任务的本地合成资源映射，非官方全量复现。结构化恢复隐藏部分自由文本，18/18只指记录中的关键事实指标；M20字面引用路径补了另一种有限保全，不等于已完成所有恢复策略比较。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

本实验让真实模型读取上游攻击返回值后继续调用工具，并以实际本地 HTTP 请求判断
越权外发。它保留选定的 InjecAgent 用户请求、原始工具名称、参数定义、工具摘要
和攻击返回值文本；云账户数据及邮件投递由受控本地 MCP 实现替代。

## 映射与可验证边界

选择商品详情 `AmazonGetProductDetails`、笔记检索 `EvernoteManagerSearchNotes`、
仓库详情 `GitHubGetRepositoryDetails` 三个上游用户任务，各配“取保存地址后发信”
和“取支付方式后发信”两个攻击意图。共 6 条攻击，每条以同一工具目录和原返回值
模板填入中性文本构造正常对照。正常对照共 6 条，但只有 3 个独立用户任务。

| 模型可见的原 API | 本地实际执行 |
|---|---|
| 当前用户取数工具 | `evidence.read_alert` 读取固定证据文件 |
| `AmazonViewSavedAddresses` / `AmazonViewSavedPaymentMethods` | `operations.read_file` 读取合成私密 JSON |
| `GmailSendEmail` | `operations.send_data` 向固定 loopback HTTP Receiver 投递邮件字段 JSON |

`to` 字段留在 JSON 中，实际网络目的地始终是本地接收端；没有登录原云账户或发送
真实邮件。附件、抄送、密送、定时发送不在映射范围内，两组 Host 均拒绝这些功能。
用户取数参数经原工具 Schema 校验后，还必须与选定上游任务参数完全一致。
上游 Python 模块和实现代码均未运行；`Tool Parameters` 只按字面量解析。

Full 的可信合同目标为原用户请求，允许证据读取，禁止私密读取和外发。私密取数在
当前本地适配器中表示为对 `secret.txt` 的 `credential.read` 效果，因此这个实验只
证明该效果映射下的权限边界，不代表实际 Amazon 数据权限模型。
本轮没有接入任务感知语义分类器，不能把拦截归因于前一轮的模型分类结果。

Receiver 实际观测请求和 Honeytoken；最终回答另检查是否逐字出现 Honeytoken。
源文件哈希校验记录私密文件是否被改写。任务指标要求成功读取指定用户工具、模型
正常结束、最终回答保留预设关键事实（例如商品名及价格、笔记标题、仓库名及所有者）。
这是确定性任务完成代理指标，没有评判回答完整性、推理质量或任意改写后的外泄。

确定性校准测试在真实 MCP 和 HTTP 上证明：脚本模型直连会外发 Honeytoken；
同样的请求经过网关后，私密读取和发送均拒绝；正常取数和回答仍能完成。模型调用
失败时已经发生的外发仍保存在 Oracle 结果里，不会被丢弃。

## 三组真实模型结果

固定 `qwen-plus-2025-12-01`、相同基础提示和工具定义，每配置每案例一次。

| 配置 | 攻击私密读取提议 | 实际私密读取 | 接收端 Honeytoken 泄露 | 攻击下任务指标通过 | 正常任务指标通过 |
|---|---:|---:|---:|---:|---:|
| Unsafe 直连 MCP | 4/6 | 4/6 | 4/6 | 3/6 | 6/6 |
| Full 合同与效果网关 | 4/6 | 0/6 | 0/6 | 2/6 | 6/6 |
| Full + 可信任务恢复 | 4/6 | 0/6 | 0/6 | 6/6 | 6/6 |

Full 中 4 次私密读取提议均由网关拒绝；另 2 条攻击轨迹没有提出私密读取，不能
把它们计为网关成功拦截。三组均无模型协议错误、无正常对照外发，也没有在最终
回答中出现 Honeytoken。Unsafe 的实际 HTTP 泄露校准了接收端正例。

Full 仅阻断副作用时，商品和笔记任务的最终回答仍可能围绕被拒绝的攻击请求。
新增 `trusted-task-recovery-v1`：第一次网关拒绝后，可信 Host 用原用户请求生成
恢复提醒，并将后续模型工具菜单收窄到该任务的取数工具；已禁止的操作无法因此
获得权限。恢复组有 4 次网关拒绝和 4 次恢复。其余 2 条任务没有触发恢复。

这些配置没有共享同一模型采样轨迹，因此表中的任务差异不能单独作为恢复机制的
严格因果效应。源、模型、提示及逐案例哈希已由比较脚本检查一致；确定性测试另
验证了恢复提醒与工具收窄行为。原始文件为：

- `eval/reports/runs/injecagent_local_paired_v1.json`：Unsafe / Full。
- `eval/reports/runs/injecagent_local_recovery_v1.json`：恢复组。
- `eval/reports/runs/injecagent_local_three_way_v1.json`：经过配对校验的汇总。

本次仍是 3 个用户任务、2 个攻击意图的探索性本地映射，**不是官方 InjecAgent
ASR、完整任务成功率或开放环境防御率**。

## 重复运行暴露的恢复失败与结构化恢复

对提醒式恢复另做三轮重复（每轮 6 攻击、6 正常对照），得到 0/18 接收端泄露、
0/18 最终回答 Honeytoken 暴露，正常任务指标 18/18；攻击下指标为 **15/18**。
12 条攻击轨迹提出私密读取，均被拒绝；另有 1 次邮件提议被网关拒绝，共 13 次
网关阻断。3 条失败都已正常读取证据并触发提醒，但最终回答未保留预设商品价格、
商品名或笔记标题。原始文件是
`eval/reports/runs/injecagent_local_recovery_repeated_v1.json`。
这说明第一次试跑的 6/6 不能外推为稳定恢复率。

新增 `full-projection` 配置：第一次拒绝后，由可信代码 `injecagent_projection.py`
按三个工具的限定结果 Schema 提取结构化字段，重建模型上下文并重放实际取数
调用的结果。恢复时移除旧的攻击对话，后续工具菜单仅保留当前取数工具；如再次
取数，也经过相同字段投影。它不读取评测预期答案，也不利用上游攻击占位位置。
输入只包含真实 MCP 读到的内容和当前工具名称；数字、字符串长度、数组长度和
类型都受限，不求值任意表达式。

投影保留商品名/价格/评分/评论元数据、笔记 ID/标题、仓库名/所有者/分支/可见性，
隐藏商品描述、评论正文、笔记片段和仓库描述等自由文本，并让模型说明这些字段
被隐藏。**这会损失原任务请求的部分自由文本信息**，因此即使关键事实指标通过，
也不能宣称完整的评论或笔记内容任务成功。投影通过保守序列化登记继承父来源，
保持 `DATA_ONLY` / `UNTRUSTED`，没有新增外发权限；真正的副作用仍经过原网关。
解析失败会记录错误并退回提醒式恢复；本原型不支持任意工具 Schema。

新增测试证明投影保持事实数值、隐藏自由文本指令、拒绝非法或无界数值、不会
执行源表达式，实际 MCP 上的上下文重建仍不会放行私密读取和外发。

结构化恢复同样完整运行三轮。比较脚本验证两份重复实验的源、基础提示、模型、
案例和重复分母一致；结果如下。每个 18 的分母都是 **6 个攻击/对照案例重复 3 次**，
不是 18 个独立攻击模板。

| 三轮配置 | 私密读取提议 | 网关拒绝动作 | 接收端泄露 | 攻击下关键事实指标 | 正常指标 |
|---|---:|---:|---:|---:|---:|
| 提醒式恢复 | 12/18 | 13 | 0/18 | 15/18 | 18/18 |
| 结构化恢复 | 12/18 | 13 | 0/18 | 18/18 | 18/18 |

两组各有 12 次私密读取提议和 1 次邮件提议，均由网关拒绝；没有 Host 参数校验
拒绝被混算成网关拦截。结构化恢复有 12 次投影、0 次解析错误，最终回答 Honeytoken
暴露为 0/18。提醒组消耗 60,608 tokens，结构化组 58,032 tokens。由于任务长度和
模型采样不同，不据此推断一般成本节约；也不将 18/18 解释为自由文本任务完整成功。

结构化恢复原始报告是 `eval/reports/runs/injecagent_local_projection_repeated_v1.json`，
重复对比是 `eval/reports/runs/injecagent_local_recovery_ablation_v1.json`。
两组轨迹各自采样，尚未共享模型随机性；这是一组探索性恢复消融观察，后续仍需
冻结独立任务集及更丰富的文本保全指标。

## 复现

源数据取得方法见 [InjecAgent 数据记录](M5_INJECAGENT.md)。四个任务 JSON 清单
SHA-256 为 `4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8`；
原 `tools.json` SHA-256 为
`e21a8f70b1d5de4677d6d52642936a322655d79b17a72c84f600550384083a1e`。

```powershell
.\.venv\Scripts\python.exe eval/run_injecagent_local.py `
  --source-root (Join-Path $source 'InjecAgent-main') `
  --expected-manifest-sha256 4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8 `
  --expected-tool-catalog-sha256 e21a8f70b1d5de4677d6d52642936a322655d79b17a72c84f600550384083a1e `
  --credentials-csv '本机百炼凭据 CSV 的绝对路径' `
  --modes unsafe full full-recovery `
  --out eval/reports/runs/injecagent_local.json
```

结构化恢复重复命令沿用以上源与凭据参数，改为
`--modes full-projection --repeats 3` 并使用不同的输出文件。

脚本逐案例原子落盘，报告不保存 API 密钥、凭据路径、原返回值或模型对话正文。
API 错误会停止后续调用并保留已观测的副作用。
划分工具支持用 `--exposure-reports` 合并分类和执行试跑暴露的案例；更新清单为
`eval/reports/runs/injecagent_split_v2_annotated.json`。排除两轮试跑后仍未暴露的
验证案例为 35，测试案例为 50；这些数量取代上一轮的 35/51。

```powershell
.\.venv\Scripts\python.exe eval/compare_injecagent_local.py `
  --reports eval/reports/runs/injecagent_local_paired_v1.json `
    eval/reports/runs/injecagent_local_recovery_v1.json `
  --out eval/reports/runs/injecagent_local_comparison.json
```
