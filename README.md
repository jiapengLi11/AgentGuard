# 溯界（Sujie / AgentGuard）

> 当前为团队协作集成分支 `integration/teammate-m21`，接收同事提供的 M21 源码快照；尚未合入 `main`。
> 队友拉取、开发分支、安装验证及未公开证据的说明见 [M21 集成交接](docs/INTEGRATION_M21.md)。
> 以下阶段记录来自原交付，历史测试与云实验结果不代表本次上传已重新运行。

面向大模型智能体提示注入与工具滥用的运行时安全网关，用于中国研究生网络安全创新大赛题目5。模型提出动作，可信 Host/网关按任务契约、Grant、来源用途和 DSL 实施 **ALLOW / ASK / BLOCK**，记录真实副作用。

更新：2026-10-15，截至M21与协议索引修正。**比赛主线为 `sujie/`；根目录 `agentguard/` 是历史v0.1原型。**

## 交接入口

- [已完成工作简明汇总](sujie/docs/COMPLETED_WORK_SUMMARY.md)：已有成果、最近验证与剩余缺口。
- [项目交接手册](sujie/docs/PROJECT_HANDOFF.md)：安装、启动、预算、代码、证据保存与接手顺序。
- [全部文档索引](sujie/docs/DOCUMENT_INDEX.md)：每份指南/记录的适用阶段。
- [当前状态](sujie/docs/F2_IMPLEMENTATION_STATUS.md) / [官方能力证据矩阵](sujie/docs/TOPIC5_EVIDENCE_MATRIX.md) / [F3计划](competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md)。

四类新增业务已按用户要求实现并验收，随后停止；F3整体未完成。本轮为文档交接，未恢复剩余开发或正式评测。旧设计的技术栈、数量目标和排期不能视为已交付或官方指定条件。

## 已实现的范围

| 范围 | 当前结果 |
|---|---|
| 授权与执行 | 九类契约、真实stdio MCP、效果映射、DSL、三态、审批绑定、执行前复核与工具版本检查 |
| 来源与模型 | Artifact/DAG、保守传播、输入快照/本地token、请求/回应保护、固定百炼模型及共享预算 |
| 工具与长链 | 封闭文件/HTTP/进程/Git、IOC/Git自主ASK续跑、实际子/孙对话与两个独立Memory会话 |
| 业务与信息保全 | 13个开发profile；时间线/Issue/附件/知识冲突四新业务；报告可选无工具字面引用核验 |
| 操作者与证据 | Python控制面、Vue任务/审批/来源/序列/影响/导出、五配置开发比较与离线重算 |

最新M21脚本16/16业务完成；云首轮3/4，时间线修复后单独完成，跨版本不合并成功率。完整回归479项通过发生在修复前，修复后52专项通过。均不是比赛ASR或正式独立任务比较，见[简明汇总](sujie/docs/COMPLETED_WORK_SUMMARY.md)。

## 快速开始（Windows PowerShell）

需要Python3.12；前端Node20.19+或22.12+，Git业务另需Git。安装和首次分词器准备需网络或已核验离线资源。

```powershell
Set-Location sujie
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe dev.py prepare-tokenizer
Push-Location console-vue
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe dev.py demo
.\.venv\Scripts\python.exe dev.py console
```

Linux/macOS改用 `.venv/bin/python`。打开 `http://127.0.0.1:8765`，使用本机 `.control-runtime/operator-token.txt` 登录。无密钥时运行固定动作/确定性演示；云配置及自定义端口直接用 `control-plane-python/run_console.py`，详见[手册](sujie/docs/PROJECT_HANDOFF.md)。`dev.py console` 不透传参数，`.env.example`是假值占位。

现有8765实例不会自动加载新代码，先导出需保留的任务再协调重启，或使用其他空闲端口。关闭任务/服务会清理临时工作区；持久预算账本不表示任务/审批可跨重启恢复。

## 目录与验证

| 目录 | 定位 |
|---|---|
| `sujie/` | 比赛代码、契约、Host/控制面、Vue、MCP、执行器、评测与阶段记录 |
| `competition/docs/` | 历史设计与F2/F3计划；目标不等于实现 |
| `competition/research/` | 当时的官方/调研原始快照，保持原样 |
| `agentguard/`、根目录`tests/`/`benchmark/` | 历史v0.1代码、测试与样例 |
| 根目录`docs/` | 当前导航和历史原型边界说明 |

从 `sujie/` 运行 `python dev.py check` 做本机静态/格式/pytest验证；Vue构建另行执行。CI配置已写，不声称远端已通过。报告多数在忽略目录，交接不能只复制可见源码。

## 安全与剩余工作

合成封闭研究原型；Host、执行器和宿主可信。子Agent同Host，本地token不是云内部token，审批没有跨崩溃exactly-once。历史M1 Linux容器不覆盖新版整体拓扑；用户当前无可用Linux环境。

正式独立任务/五配置主比较、完整三来源七绕过、全角色/有效请求绑定、新版隔离性能、材料与现场复现仍待完成。不要把脚本/测试/变体数量替代独立任务数，或把未提出危险动作记为网关拦截。

[贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md) · [依赖与许可](sujie/docs/DEPENDENCIES.md) · [MIT](LICENSE)
