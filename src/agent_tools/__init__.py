"""本地 Agent 接入（spec 002 Phase B 的 B2）：把 core 层的能力包装成 Agent 能调用的工具。

`tools.py` 是纯函数集合，直接复用 `src/core` 和 `src/config`，不经过 HTTP，方便单测；
`mcp_server.py` 只负责把这些函数注册成 MCP 工具（stdio 传输），本身不含业务逻辑。
"""
