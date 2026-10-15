# MCP-SafetyBench 外部样本接入：工具文本离线检测

> **2026-10-15 交接说明：** 历史MCP-SafetyBench文本/注册子集，保留原样本与哈希。没有因此完成上游官方Agent全任务执行或得到ASR；本地目录投毒测试与M19共同业务比较分开统计。外部数据/许可须另行随正式包整理。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

## 来源与复现

来源为 [MCP-SafetyBench 官方仓库](https://github.com/xjzzzzzzzz/MCPSafety) 的
`mcpuniverse/benchmark/configs/test`。官方仓库提供 5 个领域、245 个任务，完整执行
依赖真实 MCP 服务和外部账户；其 README 警示仓库操作可能修改个人资源。
本项目**不执行**上游任务或其 Python 模块，仅将 JSON 中的工具描述篡改文本和工具
返回值篡改文本读作低信任数据。上游仓库根目录未见 LICENSE 文件，因此不将上游
JSON 原文打包进本仓库；复现者自行从官方地址取得。

本次下载的 `main` ZIP SHA-256 为
`505482e75e0b2f20ae2fc87076b34017c85d700bcb2ae52264900dc1d762b578`。
测试文件路径与逐文件 SHA-256 组成的清单哈希为
`8ac0981cecac1f972a0ae2794082e347b9b276afd5b6e20616b1cd6522799a6c`。
12 条原始工具说明及其来源文件组成的对照清单哈希为
`c0332db69a526225e60ab842430dc2102db5f6facb9e369753307c817d2b4d9e`。
由于下载的是浮动 `main`，复现时优先校验 ZIP 哈希；若上游变化，报告会显示不同的
清单哈希，不能把不同版本的结果直接配对。

```powershell
$zip = Join-Path $env:TEMP 'mcpsafety-main.zip'
$source = Join-Path $env:TEMP 'mcpsafety-source'
Invoke-WebRequest 'https://codeload.github.com/xjzzzzzzzz/MCPSafety/zip/refs/heads/main' -OutFile $zip
(Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
Expand-Archive -LiteralPath $zip -DestinationPath $source
.\.venv\Scripts\python.exe eval/run_external_mcpsafety.py `
  --source-root (Join-Path $source 'MCPSafety-main') `
  --expected-manifest-sha256 8ac0981cecac1f972a0ae2794082e347b9b276afd5b6e20616b1cd6522799a6c `
  --out eval/reports/runs/mcpsafety_offline.json
```

脚本输出源文件路径、文件哈希、攻击类别、文本哈希与逐面检测结果；不输出原始攻击
文本，也不调用模型或外部服务。格式异常或缺少源树会失败。

实际 MCP 注册路径可用同一份源树复核：

```powershell
.\.venv\Scripts\python.exe eval/run_external_mcpsafety_protocol.py `
  --source-root (Join-Path $source 'MCPSafety-main') `
  --expected-manifest-sha256 8ac0981cecac1f972a0ae2794082e347b9b276afd5b6e20616b1cd6522799a6c `
  --out eval/reports/runs/mcpsafety_protocol.json
```

协议脚本逐条把描述放进本项目的无副作用 MCP 服务，经过真实的 `tools/list` 和
`StdioMCPProxy` 注册路径；不会导入上游 Python 文件，也不会调用该工具。

上游另有 66 个“新增工具”任务，分布为工具伪装 21、功能重叠 23、偏好操纵 22。
这些攻击可使用正常句式诱导模型选错工具，因此本地 Host 现在固定可信 MCP 服务的
预期工具名集合。`tools/list` 如果出现新增、缺失或重复工具，连接在注册前失败；每次
调用前也会重新检查完整目录。合成 `Unsafe` 和 `Static` 评测模式不启用目录固定，
避免把 Full 的新防御隐含放进基线。以下命令以同一份上游新增工具元数据做 66 组成对协议
验证：

```powershell
.\.venv\Scripts\python.exe eval/run_external_mcpsafety_protocol.py `
  --mode additions --source-root (Join-Path $source 'MCPSafety-main') `
  --expected-manifest-sha256 8ac0981cecac1f972a0ae2794082e347b9b276afd5b6e20616b1cd6522799a6c `
  --out eval/reports/runs/mcpsafety_additions.json
```

| 新增工具注册配置 | 接纳 | 拒绝 | 协议错误 |
|---|---:|---:|---:|
| 未固定目录；仅有描述文本检测 | 58 | 8 | 0 |
| 固定目录；同样的 66 条元数据 | 0 | 66 | 0 |

脚本只复现**工具目录变化**，不执行上游 `implementation_code`，不运行原始任务或
官方 Evaluator。固定目录的结果证明这类新增工具无法进入当前本地 Host 的已批准
工具列表；不能据此推断模型任务成功率。描述篡改 110 个任务与新增工具 66 个任务
不重叠，已适配的输入面共 176/245；另 69 个任务尚无对应协议适配。

## 观测结果及边界

| 项目 | 数量 |
|---|---:|
| 上游任务 JSON | 245 |
| 包含可抽取的工具描述或返回值篡改文本 | 110 |
| 工具描述文本 | 96 |
| 工具返回值文本 | 14 |
| 原规则 `rules-v0.1` 命中 | 0/110 |
| 扩展规则 `rules-v0.2` 命中 | 104/110 |
| 其中工具描述命中 | 90/96 |
| 其中返回值命中 | 14/14 |
| 上游原始服务的同名工具说明 | 0/12 误命中 |

协议层完整运行的 96 条攻击描述中，90 条被注册拒绝、6 条被接纳；12 条原始正常
工具说明全部被接纳。协议错误 0 条，离线规则与协议结果分歧 0 条。逐条选择清单的
SHA-256 为 `2c4f507efd907749ac2a4bea128e66d8345a448a36635f93fca9a6c7099051e1`。
这个结果只验证元数据入场控制，不证明模型会受到攻击或后续危险工具调用被阻止。

| 上游攻击类别，仅统计已抽取文本 | 规则命中 |
|---|---:|
| 工具返回值注入 | 14/14 |
| 命令注入 | 31/31 |
| 文件系统投毒 | 5/7 |
| 伪造工具依赖 | 22/23 |
| 网络请求投毒 | 5/6 |
| 参数投毒 | 16/18 |
| 工具重定向 | 11/11 |

以上为 `rules-v0.2` 的历史结果。该版添加了对低信任文本中代理动作指令的保守模式，例如要求额外调用工具、
改参数、执行命令。它是观察上游样本后开发的规则，因此 104/110 是**开发集内检测
命中**，不是独立测试集的泛化率。当时仍有 6 条漏检；部分采用被动语态或其他动词。
为检查注册误报，脚本不运行上游服务，而是静态解析上游 `server.py`，提取攻击目标
同名工具的原始 docstring。12 条原始说明中 0 条被命中；目标工具名全部找到了。
这是同一仓库的小规模正常对照，不足以估计一般 MCP 目录的误报率。
扩大到该仓库全部 156 条实际 MCP 工具说明后，离线与协议层均发现 **1 条正常说明
被误拒、155 条接纳**。误拒的是 GitHub `list_notifications` 的正常工具使用建议，其中
含有 “Always call this tool” 措辞。全部正常说明的离线清单哈希为
`99b126fefe4b638cde34707c5a4d17b09e7a0f835ed96ccb53b1dd95904f1b74`。
这说明该版词面规则会损害部分合法工具可用性，需要降低误报并用独立工具目录复核。
扩展前后的 14 条自建检测样本均为 TP=5、FN=2、FP=1、TN=6；另有 19 条
自建正常告警对照没有被命中。

对全部正常说明执行协议复核：

```powershell
.\.venv\Scripts\python.exe eval/run_external_mcpsafety_protocol.py `
  --source-root (Join-Path $source 'MCPSafety-main') `
  --expected-manifest-sha256 8ac0981cecac1f972a0ae2794082e347b9b276afd5b6e20616b1cd6522799a6c `
  --all-clean --clean-only --out eval/reports/runs/mcpsafety_all_clean.json
```

工具描述命中会在 MCP 注册时拒绝有毒元数据；返回值命中只生成检测发现，是否
阻断危险动作仍由 TaskContract、Grant、来源和效果裁决决定。本实验没有运行官方
基础任务，没有使用官方 Evaluator，也没有计算官方 ASR、TSR 或完整 245 题的防御分数。
工具文本离线检测之外的 135 个任务中，66 个已通过上面的新增工具目录实验覆盖；
另 69 个仍需按其实际攻击机制分别适配，不能算成当前检测器的漏检，也不能算成
防御成功。

## `rules-v0.3` 开发集复核

修订动作动词与参数改写模式后，离线命中 **110/110**：描述 96/96、返回值配置
14/14。对“用户询问待办时调用本工具”这类本工具使用建议做窄范围豁免；同一段
说明若还有其他动作指令，仍会告警。原始工具说明 156/156 未被误命中。
完整 MCP `tools/list` 注册复核中，96/96 条攻击描述拒绝，156/156 条正常说明
接纳，协议错误和离线/协议分歧均为 0。原始报告分别是
`eval/reports/runs/mcpsafety_offline_v3.json` 和
`eval/reports/runs/mcpsafety_protocol_v3.json`。
新版规则下重新运行 66 条新增工具成对协议实验：未固定目录时 54 条接纳、
12 条被描述规则拒绝；固定目录时 66 条均因目录偏离被拒绝，协议错误 0。
原始报告为 `eval/reports/runs/mcpsafety_additions_v3.json`。

返回值字段中有 8 条是“原返回值表达式 + 攻击字符串常量”，脚本只静态提取末尾
字符串；5 条为 JSON 值，按 JSON 序列化；1 条无法解析为此结构，保留配置原文。
这只是攻击配置的静态片段检查，**不等于运行上游工具后的实际返回值检测**。
脚本从不求值表达式，也不运行上游代码。

`rules-v0.3` 同样参考了这 110 条攻击和 156 条正常说明，因此 100%/0% 是
开发集内结果，没有独立留出集，不能推断泛化率。词面豁免也可能放行藏在
“调用本工具”建议里的攻击，尚需对抗测试。当前固定目录只能验证工具名单变化；
对名称和元数据不变、仅实现被替换的 Rug Pull 攻击没有给出防御证明。

## 独立正常目录

另从 [MCP 官方参考服务仓库](https://github.com/modelcontextprotocol/servers)
的 filesystem、memory 两个 TypeScript 服务静态提取 23 条 `registerTool` 描述。
没有用于调整 `rules-v0.3`。下载的 `main` ZIP SHA-256 为
`44286f82ec8be3e1a7979523aa004d138ddaa19f08fd4a8e5a2b8abb57cf6cae`；
两个源文件的路径及 SHA-256 清单哈希为
`6bb658f3fdc9367e992de9009080a9b53e69bf27f191a5ab20c5bfc60297ec56`。
离线扫描 0/23 误命中，实际 MCP 注册接纳 23/23，协议错误 0。
这是不同仓库的正常样本，但只有两种服务，不能代表整个 MCP 生态的误报率。
脚本只解析连续字符串常量，不执行 TypeScript，也不将原文写入报告。

```powershell
$zip = Join-Path $env:TEMP 'mcp-reference-servers.zip'
$source = Join-Path $env:TEMP 'mcp-reference-servers-source'
Invoke-WebRequest 'https://codeload.github.com/modelcontextprotocol/servers/zip/refs/heads/main' -OutFile $zip
(Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
Expand-Archive -LiteralPath $zip -DestinationPath $source
.\.venv\Scripts\python.exe eval/run_external_clean_catalog.py `
  --source-root (Join-Path $source 'servers-main') `
  --expected-manifest-sha256 6bb658f3fdc9367e992de9009080a9b53e69bf27f191a5ab20c5bfc60297ec56 `
  --out eval/reports/runs/mcp_reference_clean.json
```

下一步应扩大独立正常工具目录的服务类型，再对选定上游任务做安全的本地
执行映射和实际副作用 Oracle。上游原任务涉及真实外部服务时，映射结果必须单独命名，
不能混入官方全量结果。
