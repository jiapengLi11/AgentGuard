# mcp-servers/operations-server

> **2026-10-15 交接更新：** 旧read/write/send及固定哈希接口仍为受控测试路径。当前网络和注册程序任务主要使用同级network-server/execution-server；Git交付与版本Memory也有独立Server，不能将此页固定接口当作当前所有工具集合。四业务辅助资料通过受限read_file实际读取。
> 完整现状、启动与证据限制见[交接手册](../../docs/PROJECT_HANDOFF.md)。

M1 真实 stdio MCP Server，提供受根目录约束的 `read_file`、`write_file` 和仅指向
执行器内部固定 Receiver 的 `send_data`。Agent 只传目的地标签，不能提供任意 URL。

`exec_hash_report` 只接受 `case-001/output/` 下最多 64 KiB 的普通报告文件，
将文件内容送入固定的 SHA-256 Python 子进程；没有 shell、命令参数或外部目的地入口。
Gateway 将其映射为 `exec`，要求合同目的、效果和 Grant 同时授权。该固定计算任务
只验证执行前门禁，不是通用无网络、资源配额容器沙箱。

它只用于合成测试目录，不是操作宿主真实文件或公网的生产执行器。
