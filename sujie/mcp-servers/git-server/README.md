# mcp-servers/git-server

> **2026-10-15 交接更新：** 此为早期无参数push_report靶场，保留兼容测试。当前git-review/publish使用同级git-delivery-server及sandbox/sealed_git.py，包含确切commit/ref/remote/旧值/配置、lease与自主ASK，见M16。不要用本页简单工具说明替代新版Git安全边界；均只支持封存本机远端。
> 完整现状、启动与证据限制见[交接手册](../../docs/PROJECT_HANDOFF.md)。

合成靶场中的真实 stdio Git 工具，只暴露无参数的 `push_report`。可信 Host 用
`SUJIE_GIT_REPO_ROOT` 与 `SUJIE_GIT_REMOTE_ROOT` 封存本地仓库和裸仓库位置；
工具仅将源仓库 `HEAD` 推到本地远端 `refs/heads/report`，并复查远端 ref。

Gateway 将调用映射到 `git.push`，默认任务合同明确禁止；只有可信合同解除禁令，
加入 `EXECUTE` 目的和固定 ref 效果，且 Grant 授权时才执行。Agent 不能传远端 URL、
分支名或 Git 命令。该测试工具依赖可信的本地仓库和权限隔离，不代表对任意
恶意 Git 仓库或钩子的生产级沙箱。
