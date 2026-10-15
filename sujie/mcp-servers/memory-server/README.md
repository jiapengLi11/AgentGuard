# Memory MCP Server

> **2026-10-15 交接更新：** 此为早期通用合成read/write服务，保留测试。当前memory-review/update使用同级versioned-memory-server及sandbox/versioned_memory.py，固定policy/key、版本原文/CAS、两实际会话与独立Oracle见M18；二者不可混用。SQLite持久化不等于跨任务/Host重启的完整记忆产品。
> 完整现状、启动与证据限制见[交接手册](../../docs/PROJECT_HANDOFF.md)。

真实 stdio MCP 服务，提供 `read(key)` 和 `write(key, content)` 两个合成记忆操作。`SUJIE_MEMORY_DB` 指定本地 SQLite 文件；键仅允许 1–64 个 ASCII 字母、数字、下划线或连字符。此服务只负责持久化正文，授权、用途和来源判定由 Gateway 完成。

比赛闭环中应将 Memory DB 和 Gateway Trace DB 放在同一隔离工作区的可信存储中，并按工作区隔离。当前实现未提供生产级加密、保留期或多副本一致性。
