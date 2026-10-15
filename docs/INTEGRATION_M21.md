# M21 集成分支与协作入口

日期：2026-10-15。

当前分支 `integration/teammate-m21` 从 `main` 的 M1 基线 `afb4590` 建立，导入同事交接的 M21 源码快照。原交付没有 Git 历史，本次未虚构中间提交、开发作者身份或共同作者邮箱。导入与后续协作整理分别提交。

## 获取代码并开始工作

新队友可以通过 HTTPS 拉取公开代码：

```bash
git clone --branch integration/teammate-m21 https://github.com/jiapengLi11/AgentGuard.git
cd AgentGuard
git switch -c feat/your-task
```

已有仓库：

```bash
git status --short
git fetch origin
git switch --track origin/integration/teammate-m21
git switch -c feat/your-task
```

已有未提交改动时先自行保存，不使用 reset/clean 清理他人现场。已有同名本地集成分支时直接 `git switch integration/teammate-m21`。

完成后推送个人分支，并把 PR 的 base 选为 `integration/teammate-m21`。有仓库写权限的成员可直接推送个人分支；其余成员可以 Fork 后提交 PR。集成分支合入 `main` 后，后续新工作改以 `main` 为基础。

## 独立安装与验证

在 `sujie/` 使用 Python 3.12 创建自己的环境，不复制交付者的虚拟环境。Windows PowerShell：

```powershell
cd sujie
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe dev.py prepare-tokenizer
.\.venv\Scripts\python.exe dev.py check
.\.venv\Scripts\python.exe dev.py demo
Push-Location console-vue
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe dev.py console
```

Linux/macOS 使用 `.venv/bin/python`。Node 要求与当前 `PROJECT_HANDOFF.md` 一致。首次安装和固定分词器下载需要网络；运行本地确定性演示无需云 API Key。缺少分词器资产时，对应 token 映射测试会跳过；普通 CI 通过不能代替该专项验收。

控制台默认在 loopback 运行，操作者 token 由本机启动器生成并保存在被忽略的 `.control-runtime/`。凭据不能提交、共享给模型或粘贴到公开 Issue。

## 本次上传范围

- 导入代码、测试、前端锁文件、协议、部署脚本、历史阶段文档和交接说明。
- 未上传原始交接外层目录、虚拟环境、node_modules、dist、模型缓存、操作者 token、预算数据库、离线 wheel/镜像或原始评测 runs。
- `eval/reports/runs/` 在公开源码中不存在。交接手册提到的历史云实验与源码归档主要保存在原交付中，需另行整理脱敏证据包；不要把缺少这些文件误判为已重新复现实验。
- 禁止改写原报告分数、失败记录或冻结摘要。需要新结果时创建新运行目录。
- `eval/protocols/*.json` 和 tokenizer manifest 可能被按原始字节计算摘要，Git 属性保留其换行字节。不要批量重排或格式化这些文件。

## 已有并行开发

上传时仓库还存在以下未合并 PR，均保留原状：

- [PR #2](https://github.com/jiapengLi11/AgentGuard/pull/2)：M1 授权与执行边界。
- [PR #4](https://github.com/jiapengLi11/AgentGuard/pull/4)：M1 交付雏形。
- [PR #6](https://github.com/jiapengLi11/AgentGuard/pull/6)：M2 来源与出口。

这些分支与 M21 快照是并行工作，不因为功能名称相同就视为彼此已经合并。合入 `main` 前需要比较安全修复、测试和接口差异，再决定哪些应移植、哪些已覆盖；本次不关闭、合并或覆盖它们。

## 当前边界

Python 控制面与 Vue 是本快照的实际入口，Java/MySQL 未实现。历史 M1 Compose 不覆盖新增 Host、子 Agent 和所有工具；本次源码上传不等于完整部署验收或竞赛 ASR 验收。

阶段结果以各阶段原记录解释；本次上传验证以对应提交的 CI 和 PR 验证记录为准。后续优先协作完成同版回归、演示与交付收尾。

## 上传后的独立修复

首次 Linux CI 在 `4610cc0` 上复现总截止时间的错误分类：计时器关闭 socket 后，
`read1()` 可以返回空数据，随后被解释为响应截断。集成分支增加阻塞读取后的截止时间复核，
并以可控时钟分别测试超时 EOF 和提前断连；原有一秒总超时断言保持不变。
网络专项 19 项通过。此修复独立于原同事快照；旧实验报告保留原始源码摘要和失败记录，
比较旧归档与修复后的当前源码时，应将这个明确的代码变化计入版本差异。

修复版 Linux 全量为 483 passed、1 skipped；Windows 在早期 CI 的 15 分钟上限被取消，
取消前有 444 passed、2 skipped，不能算完整通过。Python CI 时限因此调整为 30 分钟，
不修改测试集合、断言或 Agent 的执行预算；最终跨平台结果以 PR 当前提交的 Actions 为准。
