# mcp-servers/evidence-server

> **2026-10-15 交接更新：** 接口仍按alert_id读取封闭根目录文本；文件可承载JSON/邮件等合成主资料。M21四业务再通过Operations读取辅助JSON/CSV，不是本Server可任意读取文件。授权/来源判定由Gateway承担；新业务输入和Oracle见M21。
> 完整现状、启动与证据限制见[交接手册](../../docs/PROJECT_HANDOFF.md)。

M1 真实 stdio MCP Server，只按合成 `alert_id` 读取显式配置根目录下的 `.txt` 告警。
不接受任意路径，也不读取宿主业务数据。
