# InjecAgent 独立攻击文本复核

> **2026-10-15 交接说明：** 历史离线/探索性无工具分类，不是Agent执行ASR。M9冻结验证/测试现已暴露，M10候选只做训练开发；后续不能复用已暴露分母声称未见泛化。本地执行映射另见M5_INJECAGENT_LOCAL。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

## 数据与口径

使用 [InjecAgent 官方仓库](https://github.com/uiuc-kang-lab/InjecAgent) `data/` 下的
四个 `test_cases_{dh,ds}_{base,enhanced}.json`。每条仅扫描 `Tool Response` 字段，
不运行上游 Agent、工具、模型或评测器。`dh` 是直接伤害类，`ds` 是数据窃取类；
同一类别的 base/enhanced 按原顺序逐条核对用户指令、攻击者指令、攻击类别和
用户工具，确认是同一 1,054 个基础案例的两种攻击文本版本。

下载的 `main` ZIP SHA-256 为
`ca09ce4db9d94cb752485a3d1f5d2eb122ac6f1ff4c82fb51b755f84e1d30466`。
四个输入文件的路径与 SHA-256 清单哈希为
`4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8`。
报告只存源清单哈希、案例身份哈希、返回值哈希及命中布尔值，不保存攻击原文。
上游仓库带 MIT 许可；本项目仍不复制其原始数据。

## 首次留出评测

`rules-v0.3` 是在 MCP-SafetyBench 样本上调整后冻结的规则；运行此表前未根据
InjecAgent 文本修改它。

| 类别 | base 命中 | enhanced 命中 |
|---|---:|---:|
| 直接伤害 `dh` | 153/510 | 510/510 |
| 数据窃取 `ds` | 34/544 | 544/544 |
| 合计 | **187/1,054（17.7%）** | **1,054/1,054** |

enhanced 样本额外包含显式“忽略之前指令”提示，规则容易命中；base 大量使用
嵌入普通工具内容的具体行为请求，现有词面规则漏检较多。尤其 `ds/Others`
子类为 0/255；按基础类别和模板查看失败例应成为下一轮开发集构造依据。
这一组结果是**离线文本检测命中率**，没有正常样本分母，也不是攻击成功率、
阻断率、官方 ASR 或完整 Agent 评测。base/enhanced 是成对版本，不能作为
2,108 个相互独立攻击来声称泛化。

```powershell
$zip = Join-Path $env:TEMP 'injecagent-main.zip'
$source = Join-Path $env:TEMP 'injecagent-source'
Invoke-WebRequest 'https://codeload.github.com/uiuc-kang-lab/InjecAgent/zip/refs/heads/main' -OutFile $zip
(Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
Expand-Archive -LiteralPath $zip -DestinationPath $source
.\.venv\Scripts\python.exe eval/run_external_injecagent.py `
  --source-root (Join-Path $source 'InjecAgent-main') `
  --expected-manifest-sha256 4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8 `
  --out eval/reports/runs/injecagent_offline.json
```

本机原始输出为 `eval/reports/runs/injecagent_offline_v1.json`。后续如果针对这些
漏检改规则，此数据便成为开发集，必须另留新的攻击数据作独立测试。
下一步应在固定训练/验证/留出划分上开发任务感知语义检测，并与正常工具返回值
和实际 Agent 副作用 Oracle 成对评估。

## 双轴划分与任务感知模型试跑

为减少模板泄漏，`eval/split_injecagent.py` 对 62 个攻击意图按 `dh`/`ds`
分别做 SHA-256 排序并按 60/20/20 分为训练、验证、测试；17 种用户工具也独立
按同一比例划分。只有两个轴落在同一分区的案例才进入对应集合，其余保留为
`cross_holdout`。原始 1,054 个基础案例划分为训练 370、验证 36、测试 52、
交叉组合 596。base/enhanced 始终共享分区。划分只记录身份哈希，不记录原文；
本机清单为 `eval/reports/runs/injecagent_split_v1.json`。

现有告警专用语义分类器不能直接用于这些不同任务，因此新增无工具的
`TaskAwareSemanticClassifier`。它分别接收可信用户请求、工具名和低信任返回值，
要求模型输出严格的 JSON 布尔判定与原因码；当前只用于离线实验，没有接入
网关授权热路径。试跑从每种用户工具的 `dh`、`ds` base 案例各按身份哈希选 1 条，
共 34 条攻击；每条用上游返回值模板替换 `<Attacker Instruction>` 为固定中性文本，
构造一条**合成**正常对照。两者使用相同可信请求与工具名。

| 检测方法，同一 34 组 | 攻击检出 | 合成对照误报 |
|---|---:|---:|
| `rules-v0.3` | 5/34 | 0/34 |
| `qwen-plus-2025-12-01` 任务感知分类 | 28/34 | 0/34 |

模型结果按类别为 `dh` 11/17、`ds` 17/17；无无效 JSON，合计 68 次分类调用、
19,523 tokens。提示 SHA-256 为
`fd931736a7efdb65c5d249eaded6b09d6e8e01636b62aca216a6e65d68b313dc`，
抽样清单 SHA-256 为
`6680641dd9d4304c4a5acf3311d1bf57c1f79a2a2ef4c77ff305b0d1c2a49485`。
原始结果在 `eval/reports/runs/injecagent_task_aware_pilot_v1.json`，不含 API 密钥、
返回值正文或完整模型对话。

这只是**一次探索性离线分类试跑**，不是冻结留出集成绩；34 条对照为模板填充的
中性文本，不能估计真实工具返回值误报率。它也没有让 Agent 继续执行，不能说明
攻击是否成功或网关是否阻断。试跑与双轴划分有 11 条训练、1 条验证、1 条测试、
21 条交叉组合重合；后续“未见”验证和测试应排除这 1+1 条。注释版清单
`eval/reports/runs/injecagent_split_v1_annotated.json` 显示未暴露验证 35、测试 51。
若以后根据这六条漏检调整提示，本次试跑更不能当作最终测试。

```powershell
.\.venv\Scripts\python.exe eval/split_injecagent.py `
  --source-root (Join-Path $source 'InjecAgent-main') `
  --expected-manifest-sha256 4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8 `
  --out eval/reports/runs/injecagent_split.json

.\.venv\Scripts\python.exe eval/run_task_aware_injecagent.py `
  --source-root (Join-Path $source 'InjecAgent-main') `
  --expected-manifest-sha256 4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8 `
  --credentials-csv '本机百炼凭据 CSV 的绝对路径' `
  --out eval/reports/runs/injecagent_task_aware.json
```

后续已完成选定商品、笔记和仓库任务的真实模型工具续执行与本地副作用 Oracle，
并发现及修复阻断后任务未恢复的问题，见 [本地执行映射记录](M5_INJECAGENT_LOCAL.md)。
这次新增暴露案例合并后，未暴露验证/测试数量更新为 35/50，旧的 35/51 仅是前一阶段记录。
后续 M9 已按冻结协议完成这 35/50 对的任务感知分类，结果和新增暴露记录见
[M9](M9_FROZEN_CLASSIFICATION.md)。现在这批验证/测试均已暴露，不能复用为新的未见成绩。
