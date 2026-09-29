"""本地 MCP 服务（spec 002 "Agent 接入方案" B2）：把 `agent_tools.tools` 里的纯函数注册成 MCP 工具。

这个文件只负责"注册"，不写任何业务逻辑——逻辑都在 `agent_tools/tools.py` 里，方便单测。

启动方式（stdio 传输，给 Claude Code / Codex 等 Agent CLI 用，见仓库根目录 `.mcp.json`）：
    PYTHONPATH=src uv run python -m agent_tools.mcp_server
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

import config
from agent_tools import activity, tools

mcp = MCPServer(
    name="personal-assistant",
    instructions=(
        "本地个人办事助手：只读共享区的流程攻略、读写你自己的「我的办事」进度。"
        "不提供删除工具，也不提供读取材料文件内容本身的工具——只看结构化的状态。"
        "「基本信息」（PersonalProfile）可读；写回只能写用户亲口回答并确认过的内容。"
    ),
)


def _logged(tool: str, args: dict, fn):
    """改办事进度的工具：从网页调起时记下撤销信息（spec 004 第 3 步），在终端里用时照常执行。"""
    return activity.record_track_write(config.get_materials_root(), tool, dict(args), fn)


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
    return _logged("set_fact", locals(), lambda: tools.set_fact(track_id, fact, value))


@mcp.tool(description="勾选或取消一件办事里的某个步骤")
def set_step_done(track_id: str, step_id: str, done: bool) -> dict:
    return _logged("set_step_done", locals(), lambda: tools.set_step_done(track_id, step_id, done))


@mcp.tool(
    description=(
        "确认或取消确认一条材料需求对应的候选记录（只能确认核心库已经算出的候选，不能指定任意记录）"
    )
)
def confirm_match(track_id: str, requirement_id: str, confirmed: bool) -> dict:
    return _logged("confirm_match", locals(), lambda: tools.confirm_match(track_id, requirement_id, confirmed))


@mcp.tool(
    description="校验共享区（词表 + 全部攻略），结果结构与 `uv run python -m core.guides` 一致，供整理攻略后自查"
)
def validate_community() -> dict:
    return tools.validate_community()


@mcp.tool(description='隐藏或恢复一件办事里的步骤（kind="step"）或材料（kind="requirement"）；只影响个人进度，不改共享攻略。写之前先向用户复述并征得同意')
def set_hidden(track_id: str, kind: str, item_id: str, hidden: bool) -> dict:
    return _logged("set_hidden", locals(), lambda: tools.set_hidden(track_id, kind, item_id, hidden))


@mcp.tool(description='给步骤（kind="step"）或材料（kind="requirement"）写个人备注，note 为空表示删除备注')
def set_note(track_id: str, kind: str, item_id: str, note: str | None) -> dict:
    return _logged("set_note", locals(), lambda: tools.set_note(track_id, kind, item_id, note))


@mcp.tool(description="在一件办事里加一个自己的步骤（phase=阶段 id，after=插在哪个步骤后面，都可省略）；只存在个人区")
def add_custom_step(track_id: str, title: str, phase: str | None = None, after: str | None = None, where: str | None = None) -> dict:
    return _logged("add_custom_step", locals(), lambda: tools.add_custom_step(track_id, title, phase, after, where))


@mcp.tool(description="在一件办事的某个步骤下加一项自己的材料；名字能被词表认出时自动匹配材料库")
def add_custom_material(track_id: str, name: str, step: str, material_type: str | None = None, optional: bool = False) -> dict:
    return _logged("add_custom_material", locals(), lambda: tools.add_custom_material(track_id, name, step, material_type, optional))


@mcp.tool(description="把一条避坑点记到办事页右侧的核对清单里（1–300 字）")
def add_pitfall(track_id: str, text: str) -> dict:
    return _logged("add_pitfall", locals(), lambda: tools.add_pitfall(track_id, text))


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


@mcp.tool(
    description=(
        "新建 / 修改攻略时用：把整份攻略 YAML 写进草稿区（不会写进攻略库，用户在页面上确认后才发布），"
        "返回校验结果。guide_id 必须和 YAML 里的 id 一致（小写字母、数字、连字符）。"
        "alias_suggestions 是给词表认不出的叫法提的建议：[{raw_name: 原叫法, key: 建议归入的已有词表 key}]，"
        "只写你有把握的；用户会在页面上逐条勾选。有 errors 就改完再调用一次，直到 valid 为 true"
    )
)
def save_guide_draft(guide_id: str, yaml_text: str, alias_suggestions: list[dict] | None = None,
                     guide_type: str = "process") -> dict:
    return tools.save_guide_draft(guide_id, yaml_text, alias_suggestions, guide_type)


@mcp.tool(description="读一份攻略草稿的全文和校验结果；按用户要求修改草稿前先读")
def get_guide_draft(guide_id: str, guide_type: str = "process") -> dict:
    return tools.get_guide_draft(guide_id, guide_type)


@mcp.tool(description="只读：重新校验一份攻略草稿（valid、errors、词表认不出的叫法）")
def validate_guide_draft(guide_id: str, guide_type: str = "process") -> dict:
    return tools.validate_guide_draft(guide_id, guide_type)


@mcp.tool(
    description=(
        "只读：通用填表引擎第 1 步。返回一段扫描脚本，用浏览器工具（javascript_tool）在官网当前页原样运行，"
        "它返回 {count, chars, parts}（不含格子里的值）。浏览器工具一次只回传约 1000 字，所以再依次运行 "
        "window.__paScanText.slice(900*k, 900*(k+1))（k = 0..parts-1）读回每一段，原样拼成一个字符串交给 plan_form_fill"
    )
)
def get_form_scan_script() -> dict:
    return tools.get_form_scan_script()


@mcp.tool(
    description=(
        "只读：通用填表引擎第 2 步。scan = 扫描结果分段读回后拼起来的字符串。按同义词表认出格子、从「基本信息」取值，"
        "返回 fill（会填的格子）、sensitive（敏感字段，默认不填，要用户同意后放进 allow_sensitive 重新调用）、"
        "missing（基本信息里没有，要问用户）、needs_format（日期格式看不出，你来填）、"
        "manual（改了会让页面刷新的下拉框，不自动填，请用户手动选或你用真实点击选）、already_filled、"
        "unmatched（认不出，你来处理）和 script。把 script 原样用 javascript_tool 在同一页运行即可填写；"
        "script 里含用户的个人信息，不要在对话里复述它。一页最多扫描+填写 2 轮"
    )
)
def plan_form_fill(scan: str, allow_sensitive: list[str] | None = None) -> dict:
    return tools.plan_form_fill(scan, allow_sensitive)


@mcp.tool(
    description=(
        "网页里的 Agent 用：提议修改「基本信息」的一个分组（参数同 update_personal_profile）。不会直接写入——"
        "页面上会弹出确认卡片（旧值 → 新值），用户点确认后才写。只提议用户在对话里亲口说的内容。"
        "返回 proposal_id 和 changed；告诉用户\"请在下面的卡片里确认\""
    )
)
def propose_profile_update(group: str, changes: dict) -> dict:
    try:
        return activity.propose_profile_update(config.get_materials_root(), group, changes)
    except KeyError:
        raise ValueError(f"没有这个分组：{group}")
    except ValidationError as e:
        raise ValueError(f"字段名或取值不对，没有记下提议：{e}") from e


@mcp.tool(
    description=(
        "填表插件「让 Agent 补填」专用：把这一页剩下的格子要填什么交给插件，由插件去填（你碰不到官网）。"
        "fills = [{\"i\": 格子编号, \"value\": 要填的文字}]；下拉框 / 单选的 value 必须是给你的 options 里的原文。"
        "只填基本信息里有的值或用户在对话里亲口说的；法律声明题不填。"
        "learn = [{\"phrase\": 格子上的说法, \"path\": 基本信息字段路径}]，是以后引擎也能自动认的建议（可省略）"
    )
)
def submit_form_fills(fills: list[dict], learn: list[dict] | None = None) -> dict:
    if os.environ.get(activity.UI_ENV) != "1":
        raise ValueError("submit_form_fills 只在填表插件调起的任务里用")
    try:
        return activity.submit_form_fills(config.get_materials_root(), fills, learn)
    except ValueError as e:
        # 抛出的异常在 Agent 那头只显示成"Error executing tool"，看不到原因；改成把原因作为结果返回
        return {"error": str(e)}


@mcp.tool(
    description=(
        "只读：填表用的基本信息精简版——每个有值的字段一行：path、中文标签、可以直接填的写法（日期给几种格式、国家给英文名）。"
        "比 get_personal_profile 短得多，填表时优先用它"
    )
)
def get_fill_reference() -> dict:
    from form_engine.match import default_dictionary
    from form_engine.reference import reference
    from core.profile_storage import load_personal_profile

    ref = reference(load_personal_profile(config.get_materials_root()), default_dictionary())
    return {"items": [
        {"path": it["path"], "label": f"{g['label']} › {it['label']}", "values": [v["text"] for v in it["values"]]}
        for g in ref["groups"] for it in g["items"]
    ]}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
