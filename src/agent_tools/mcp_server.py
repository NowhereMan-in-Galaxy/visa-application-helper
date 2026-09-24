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
        "「基本信息」（PersonalProfile）可读；写回只能写用户亲口回答并确认过的内容。"
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


@mcp.tool(description='隐藏或恢复一件办事里的步骤（kind="step"）或材料（kind="requirement"）；只影响个人进度，不改共享攻略。写之前先向用户复述并征得同意')
def set_hidden(track_id: str, kind: str, item_id: str, hidden: bool) -> dict:
    return tools.set_hidden(track_id, kind, item_id, hidden)


@mcp.tool(description='给步骤（kind="step"）或材料（kind="requirement"）写个人备注，note 为空表示删除备注')
def set_note(track_id: str, kind: str, item_id: str, note: str | None) -> dict:
    return tools.set_note(track_id, kind, item_id, note)


@mcp.tool(description="在一件办事里加一个自己的步骤（phase=阶段 id，after=插在哪个步骤后面，都可省略）；只存在个人区")
def add_custom_step(track_id: str, title: str, phase: str | None = None, after: str | None = None, where: str | None = None) -> dict:
    return tools.add_custom_step(track_id, title, phase, after, where)


@mcp.tool(description="在一件办事的某个步骤下加一项自己的材料；名字能被词表认出时自动匹配材料库")
def add_custom_material(track_id: str, name: str, step: str, material_type: str | None = None, optional: bool = False) -> dict:
    return tools.add_custom_material(track_id, name, step, material_type, optional)


@mcp.tool(description="把一条避坑点记到办事页右侧的核对清单里（1–300 字）")
def add_pitfall(track_id: str, text: str) -> dict:
    return tools.add_pitfall(track_id, text)


@mcp.tool(
    description=(
        "只读：读取用户的「基本信息」（姓名拼音、护照、联系方式、家庭、教育、工作、旅行与签证历史、社交媒体等）"
        "和字段说明（中文标签、sensitive、对应 DS-160 哪一问）。用于辅助填写 DS-160 等表格。"
        "内容是真实个人信息：只在填表需要时使用，不要在对话里整段复述 sensitive 字段；"
        "空值 / 空列表表示用户没填，不等于回答“否”，要先问用户；profile.confirmed_none 里列出的字段路径"
        "表示用户已确认“没有”，可以直接答 No。用户回答后用 update_personal_profile 写回值，"
        "回答“没有”的用 confirm_personal_profile_none 记下"
    )
)
def get_personal_profile() -> dict:
    return tools.get_personal_profile()


@mcp.tool(
    description=(
        "把用户在填表时回答的长期个人信息写回「基本信息」的一个分组（group 取 identity / passport / contact / "
        "family / education / employment / travel / social_media / background）。changes 只放要改的字段，"
        "字段 key 和取值格式以 get_personal_profile 的 fields 说明为准；对象字段逐键合并，列表字段整体替换（要发完整列表）。"
        "硬性规则：①只写用户在对话里亲口回答的内容，不写你推测、从网页或材料里猜出来的值；"
        "②写之前把要写的字段和值逐条复述给用户，用户明确同意后才调用；"
        "③本次行程专属的信息（出行目的、日期、在美地址、同行人等）和 Security/Background 法律声明题不要写进来。"
        "返回 changed 列表（before/after），写完向用户简短报告改了哪些字段"
    )
)
def update_personal_profile(group: str, changes: dict) -> dict:
    return tools.update_personal_profile(group, changes)


@mcp.tool(
    description=(
        "把用户在填表时亲口确认“没有”的字段记进「基本信息」（例如没有曾用名 → [\"identity.other_names\"]），"
        "下次填表不用再问。路径格式是 分组.字段（字段 key 见 get_personal_profile 的 fields）。"
        "只用于列表字段和可空的文本/对象字段；是非题请用 update_personal_profile 直接写 false。"
        "硬性规则同 update_personal_profile：只记用户亲口说的“没有”，记之前逐条复述并征得同意；"
        "本次行程专属信息和 Security/Background 法律声明题不要记。字段以后被填上值时会自动移出清单"
    )
)
def confirm_personal_profile_none(fields: list[str]) -> dict:
    return tools.confirm_personal_profile_none(fields)


@mcp.tool(
    description=(
        "只读：填表前查缺口。按 DS-160 页面列出「基本信息」里每个字段的状态——filled（有值）、"
        "confirmed_none（用户确认没有）、missing（没填也没确认，要问）。不含字段值。"
        "开始填表前先调用它，把 missing 的问题一次问完、写回后再填，而不是填到一半才问"
    )
)
def get_profile_gaps() -> dict:
    return tools.get_profile_gaps()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
