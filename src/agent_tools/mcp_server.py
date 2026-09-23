"""本地 MCP 服务（spec 002 "Agent 接入方案" B2）：把 `agent_tools.tools` 里的纯函数注册成 MCP 工具。

这个文件只负责"注册"，不写任何业务逻辑——逻辑都在 `agent_tools/tools.py` 里，方便单测。

启动方式（stdio 传输，给 Claude Code / Codex 等 Agent CLI 用，见仓库根目录 `.mcp.json`）：
    PYTHONPATH=src uv run python -m agent_tools.mcp_server
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from agent_tools import tools

mcp = MCPServer(
    name="personal-assistant",
    instructions=(
        "本地个人办事助手：只读共享区的流程攻略、读写你自己的「我的办事」进度。"
        "不提供删除工具，也不提供读取材料文件内容本身的工具——只看结构化的状态。"
    ),
)


@mcp.tool(description="列出共享区里全部流程攻略（含没通过校验的，标 valid=false 和 errors）")
def list_guides() -> list[dict]:
    return tools.list_guides()


@mcp.tool(description="查看一份流程攻略的详情，附带用当前材料库算出的预览（还没开始办也能看）")
def get_guide(guide_id: str) -> dict:
    return tools.get_guide(guide_id)


@mcp.tool(description="列出我的全部办事（Track）及简要进度")
def list_tracks() -> list[dict]:
    return tools.list_tracks()


@mcp.tool(description="查看一件办事的完整状态：问题、材料需求、步骤、下一步、阶段进度")
def get_track(track_id: str) -> dict:
    return tools.get_track(track_id)


@mcp.tool(
    description=(
        "回答一件办事里攻略提出的问题（例如身份/婚否）；value 传 null 表示清除这个回答；"
        "value 不是该问题的合法选项会报错"
    )
)
def set_fact(track_id: str, fact: str, value: str | None) -> dict:
    return tools.set_fact(track_id, fact, value)


@mcp.tool(description="勾选或取消一件办事里的某个步骤")
def set_step_done(track_id: str, step_id: str, done: bool) -> dict:
    return tools.set_step_done(track_id, step_id, done)


@mcp.tool(
    description=(
        "确认或取消确认一条材料需求对应的候选记录（只能确认核心库已经算出的候选，不能指定任意记录）"
    )
)
def confirm_match(track_id: str, requirement_id: str, confirmed: bool) -> dict:
    return tools.confirm_match(track_id, requirement_id, confirmed)


@mcp.tool(
    description="校验共享区（词表 + 全部攻略），结果结构与 `uv run python -m core.guides` 一致，供整理攻略后自查"
)
def validate_community() -> dict:
    return tools.validate_community()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
