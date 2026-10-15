# eval/reports

M1 确定性工程闭环结果见 `../../docs/M1_ACCEPTANCE.md`，不是 LLM 评测成绩。
后续原始模型运行数据放入被忽略的 `runs/`，再由固定评测脚本生成报告。
`detection_v1.report.json` 仅报告 14 条合成文本上的规则检测命中和误报，
不包含真实 Agent 或副作用 Oracle 成绩。
`policy_latency_windows.json` 仅是一次本机纯策略决策基准，不含工具和模型延迟。
`run_external_mcpsafety.py` 可读取使用者自行下载的官方 MCP-SafetyBench JSON，
只做工具攻击文本离线检测并保留逐文件哈希；结果与复现方式见
`../../docs/M5_EXTERNAL_BENCHMARK.md`。它不执行上游 Agent，也不产生官方 ASR。
`run_external_mcpsafety_protocol.py` 将上游工具描述或新增工具的元数据交给本地
无副作用 MCP 服务，通过真实 `tools/list` 检查注册结果；仍不运行官方任务、工具实现
或 Evaluator。攻击样本、正常工具说明和固定目录前后的结果分开统计。
`run_external_clean_catalog.py` 从另一份 MCP 官方参考服务源码静态提取正常
工具描述，并逐条复核本地注册路径；仅保存哈希和结果，不执行上游源码。
`run_external_injecagent.py` 对 InjecAgent 成对 base/enhanced 工具返回值文本做
首次留出规则评测；其命中率、来源和限制见 `../../docs/M5_INJECAGENT.md`。
`split_injecagent.py` 固定攻击意图与用户工具双轴划分，并可标记试跑暴露案例。
`run_task_aware_injecagent.py` 在确定性 34 组子集上做真实模型的无工具任务感知
分类；正常对照是模板填充的合成文本，结果不是上游 Agent ASR。
`run_injecagent_local.py` 保留选定上游请求、工具名和攻击返回值，使用本地 MCP
私密文件及 HTTP Receiver 做真实模型执行映射；逐案例保存真实外发、关键事实任务
指标和恢复事件。`compare_injecagent_local.py` 校验逐例来源、模型、提示与数据哈希，
再比较 Unsafe / Full / Full+恢复。具体映射边界见 `../../docs/M5_INJECAGENT_LOCAL.md`。
`full-projection` 另验证限定字段投影与上下文重建；三轮提醒/投影恢复的报告仍使用
同一比较脚本校验，不将重复案例算成独立模板，也不把关键事实指标当成完整语义任务成绩。

`runs/` 被版本控制忽略。`run_bailian.py` 在这里输出真实模型小样本的结构化结果，
包含模型名、调用用量、网关裁决、最终合成报告与接收端 Oracle；
不保存 API 密钥和原始模型对话。报告正文限 4096 字符，完整哈希另存。
重复运行中角色伪装样例曾诱导模型提出读取秘密文件，网关拦截；
这个小样本不能外推为比赛攻击成功率。
`run_semantic_bailian.py` 将独立无工具语义检测器分别在成对任务集和早期规则检测集上评估，
输出逐例预测、混淆矩阵、数据集与提示哈希。这是离线检测实验，在线链路另用
`run_bailian.py --semantic-guard` 评估。
同版 Host 的在线开关对照只各运行一轮，具体分母和局限见
`../../docs/M4_REAL_MODEL.md`。
`compare_bailian.py` 校验相同数据集、模型别名、Host 版本与任务提示，
再把合成 Unsafe 直连 MCP 与 Full 逐例配对，按接收端实际 Honeytoken 泄露
计算小样本结果，并核验目标告警读取、报告写入和 IOC 保全。
