# mcp-servers/malicious-variants

封闭恶意 MCP 变体。目前提供 M2 嵌套返回测试服务，其他变体待后续接入。

## M2 嵌套返回测试变体

`nested-evidence-server.py` 是真实 stdio MCP 测试服务，在嵌套字段携带合成内容及伪造的 PUBLIC/CONTROL_PLANE 声明。来源分类来自可信测试目录，正文声明不能签发标签或授权。PUBLIC/SECRET 对照由 `tests/test_m2_e2e.py` 驱动；该服务只用于本地封闭回归，不是生产读取接口。
