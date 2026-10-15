# M1 Docker 验证

> **2026-10-15 交接更新：** 本页仅是历史M1 Docker复现，须从sujie目录执行命令。当前Python控制面、百炼Host、实际子孙/Memory和新增MCP未纳入此拓扑；不可把脚本通过算作新版整体隔离。用户已确认暂无可用Linux环境，W8仍缺验收；deploy/compose.yaml是M0占位。
> 完整现状、启动与证据限制见[交接手册](../docs/PROJECT_HANDOFF.md)。

本机操作者控制台运行见 [M6 控制台](../docs/M6_OPERATOR_CONSOLE.md)。
它目前不在本页的 M1 容器拓扑里；不能把本机控制台验证当成新增容器隔离验收。

拓扑使用两个 Docker internal 网络：Agent 只连接 `agent-net`，Receiver 只连接
`tool-net`，Gateway 连接二者。Agent 镜像不包含 Gateway/MCP 源码，不挂载测试工作区，
也没有审批 API。

联网环境直接运行：

```sh
sh deploy/run_m1_container_test.sh
```

离线环境先导入并标记可信 linux/amd64 Python 基础镜像，将与 requirements.lock 对应的
CPython 3.12 Linux wheels 放入 `deploy/wheelhouse/`，然后运行：

```sh
export SUJIE_PYTHON_BASE=sujie/python-base:3.12.13
export SUJIE_OFFLINE_BUILD=1
sh deploy/run_m1_container_test.sh
```

离线模式强制 `pip --no-index`；缺 wheel 会直接构建失败。脚本使用普通
`docker compose down --remove-orphans` 清理本项目容器和网络，从不删除 Volume。

成功标准：Agent 输出 `receiver_directly_unreachable=true`、`external_network_unreachable=true`、
`secret_mount_absent=true` 和 `docker_socket_absent=true`；
独立 Oracle 输出 `receiver_requests=0`、`report_written=true` 和
`honeytoken_in_report=false`。该验证使用确定性测试模型，不是 LLM 评测。
