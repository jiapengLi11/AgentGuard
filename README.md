# 溯界（Sujie / AgentGuard）

面向 LLM Agent 的提示词注入与工具滥用防护研究原型。核心原则是 **模型提出动作，不授予权限**：由可信 Host 维护任务契约、TaskGrant、来源账本与审批，工具调用在执行前经过独立校验。

## 结项与下载

本轮于 **2026-10-23 完成公开材料归档**，不表示赛题全部能力或生产安全性已验收，也不代表已向比赛平台提交。仓库保留可继续协作的状态。

- [结项说明与材料索引](docs/PROJECT_CLOSEOUT_2026-10-23.md)：版本、源码、报告、历史证据、隐私处理和剩余缺口。
- [结项 Release](https://github.com/jiapengLi11/AgentGuard/releases/tag/closeout-2026-10-23)：冻结程序包、三个 PDF、LaTeX、正式证据包、M13–M21 历史记录及校验清单。
- [正式交付复核](competition/submission/交付复核-2026-10-22.md)：程序冻结于 `96d591b`，报告源码绑定 `1b64b1f`；23 页宋体报告、4 页部署说明、6 页测试说明。冻结包含预构建 Vue，不是独立 EXE。
- 当前 `main` 含后续 PDF/DOCX 提取实现；不能用冻结包的测试数字替代当前源码验收。当前运行时与通过质量门禁的 `985417a` 相同，详见结项记录。

## 实现范围与边界

| 模块 | 已有实现 | 限制 |
|---|---|---|
| 授权与执行 | TaskContract/TaskGrant、真实 stdio MCP、工具版本校验、DSL、ALLOW/ASK/BLOCK、审批绑定与执行前复核 | Host/执行器可信；审批不提供跨重启 exactly-once |
| 注入检测与来源 | 用户/工具返回/描述/记忆扫描，结构化字段来源，Artifact DAG、文本区间与导出 | 检测主要基于规则；本地 token 不是云模型内部 token 或完整因果归因 |
| 工具链与业务 | 受控文件/网络/进程/Git，子/孙 Agent、跨会话 Memory、13 个开发 profile | 合成封闭业务；完整工具与角色隔离、外部宿主接入未验收 |
| 控制台与评测 | Python 控制面、Vue、审批/溯源/导出、离线校准与独立副作用观察 | 脚本/Mock/规则指标不等于真实模型 Execution ASR；无生产性能结论 |

冻结程序包的解压复验历史记录为 **1107 passed / 1 skipped / 1 xfailed / 1 warning**，四业务 16/16 完成、云调用 0。已知 xfail 是审批后超限工具返回缺少部分效果审计，不计作通过。依据见[原始复核记录](docs/validation/SUBMISSION_PACKAGE_REVIEW_2026-10-22.json)。历史云实验另行归档，不混入该结果。

## 快速运行（Windows PowerShell）

源码开发需要 Python 3.12、Node 20.19+ 或 22.12+；Git 业务另需 Git。首次依赖与分词器准备需网络或经过校验的离线资产。

```powershell
Set-Location sujie
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

打开 `http://127.0.0.1:8765`，使用本机生成的 `.control-runtime/operator-token.txt` 登录。Linux/macOS 改用 `.venv/bin/python`。无云凭据可运行确定性演示；实际 Provider 配置和端口参数见[交接手册](sujie/docs/PROJECT_HANDOFF.md)。不要把 `.env.example` 当真实配置，也不要公开上传操作者 token。

完整质量门禁：在 `sujie/` 运行 `python dev.py check`。公开历史包构建与文稿检查：在仓库根运行 `python -m unittest discover -s competition/submission/tools -p "test_*.py" -v` 和 `python competition/submission/tools/check_report_latex.py`。

## 源码与文档导航

- [sujie/](sujie/)：比赛运行主线，含契约、网关、Host、MCP、执行器、控制面、Vue、测试及评测脚本。
- [competition/docs/](competition/docs/)：总体设计、能力审计和历史计划；计划不等于交付。
- [competition/submission/](competition/submission/)：文稿、TeX 图形、PDF、打包和复核工具。
- [sujie/docs/](sujie/docs/DOCUMENT_INDEX.md)：阶段记录、依赖许可和复现指南。
- [agentguard/](agentguard/)、[tests/](tests/)、[benchmark/](benchmark/)：早期 v0.1 原型；[旧输出](docs/legacy-v01/) 不代表当前成绩。
- [结项前 README 快照](docs/README_SNAPSHOT_BEFORE_CLOSEOUT_2026-10-23.md)：保留旧能力表与历史陈述，当前状态以本页和结项记录为准。

源码、测试、设计、报告和可公开证据保留；个人签名、声明成品、真实凭据、预算数据库、依赖环境、完整字体及无关项目资料不公开。历史 Release 的声明附件已移除，但删除无法召回他人已下载的副本；未擅自重写 Git 历史。

[贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md) · [第三方依赖](sujie/docs/DEPENDENCIES.md) · [MIT](LICENSE)
