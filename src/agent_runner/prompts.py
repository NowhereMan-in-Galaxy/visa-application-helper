"""各类任务的提示词（spec 004"模块划分"）。

提示词只说"你在哪、用户在看什么、能做什么、怎么答"，具体规则让 Agent 去读仓库里的 skill 和 spec，
不在这里重复，避免两处说法不一致。
"""

from __future__ import annotations

PAGE_NAMES = {
    "guides": "攻略库首页",
    "guide": "一份攻略的详情页",
    "track": "「我的办事」里一件事的进度页",
    "materials": "「我的资料 → 材料库」",
    "profile": "「我的资料 → 基本信息」",
    "travel": "「我的资料 → 出行记录」",
    "new": "新建攻略",
}


def create_guide_prompt(user_input: str, guide_type: str, *, follow_up: bool = False,
                        draft_id: str | None = None) -> str:
    """新建攻略（spec 004）。第一条消息给完整规则；后续消息接着同一次对话（--resume），只补充提醒。"""
    if follow_up:
        return "\n".join([
            "（用户在新建攻略的窗口里继续说话。）",
            f"当前草稿：{draft_id}（先用 get_guide_draft 读最新内容，用户可能刚改过词表）。" if draft_id else "还没有草稿。",
            "按用户的话修改后用 save_guide_draft 保存整份 YAML，直到 valid；如果用户只是提问，就直接回答，不要改草稿。",
            "规则同前：只能写草稿；读帖子遵守 xhs-reader；抽取遵守 guide-author 和 specs/002-guide-to-track/prompt.md。",
            "",
            f"用户：{user_input}",
        ])
    return "\n".join([
        "你是本地个人办事助手网页里「新建攻略」窗口的 Agent。用户会给你小红书分享文字 / 链接、帖子正文，或别处的总结，",
        f"你要把它们整理成一份「办事流程攻略」（攻略类型 id：{guide_type}）的草稿。",
        "",
        "按顺序做：",
        "1. 先用 Skill 工具读 guide-author，再按它的要求读 specs/002-guide-to-track/prompt.md、community/material_types.yaml，"
        "字段范围见 specs/002-guide-to-track/spec.md「数据结构」一节。可以用 list_guides / get_guide 看已有攻略的写法，也用来确认没有重复。",
        "2. 输入里有小红书链接时，用 Skill 工具读 xhs-reader，严格照做：只在未登录的浏览器里读，一次最多 6 条，"
        "发现已登录或遇到验证码 / 安全限制就停下并告诉用户。只能用用户给的原始分享链接，不要自己改链接、不要搜索。",
        "3. 用户直接粘贴的正文算一篇来源；明显是 AI 生成的\"搜索总结\"算二手来源（参考 community/guides 里 g2「小红书 AI 搜索总结」的写法），"
        "只用它补充原帖没写到的，并在 uncertain 里标出。",
        "4. 整理成 YAML 后，用 save_guide_draft 保存（guide_id 自己取，小写英文加连字符，和 YAML 里的 id 一致）。"
        "返回有 errors 就修改后再保存，直到 valid 为 true。你没有写文件、运行命令的权限，也不需要：校验就是 save_guide_draft / validate_guide_draft。",
        "5. 词表认不出的叫法：能归入已有 key 的，放进 save_guide_draft 的 alias_suggestions，由用户在页面上勾选；不要试图改词表。",
        "6. 最后用中文简短回复（不超过 12 行）：读到了哪几篇（标题）、哪些没读到及原因、草稿 id、还不确定的地方、各篇说法冲突的地方。"
        "不要把 YAML 贴出来——页面右侧会显示草稿预览。",
        "",
        "硬性要求：不写任何人的个人信息（名字、证件号、邮箱、电话；官方机构的公开地址和邮箱除外）；"
        "来源链接去掉 xsec_token 等分享参数；攻略没写的不要凭常识补。",
        "",
        *([f"注意：已经有一份草稿 {draft_id}。先用 get_guide_draft 读它，在它的基础上按用户的输入修改或补充，保存时沿用这个 id。", ""]
          if draft_id else []),
        "用户的输入：",
        user_input,
    ])


def ask_prompt(question: str, context: dict) -> str:
    page = PAGE_NAMES.get(context.get("page") or "", "本项目的网页界面")
    where = [f"用户正在看：{page}。"]
    if context.get("guide_id"):
        where.append(f"攻略 id：{context['guide_id']}（可用 get_guide 读取）。")
    if context.get("track_id"):
        where.append(f"办事 id：{context['track_id']}（可用 get_track 读取）。")
    return "\n".join([
        "你是这个本地个人办事助手界面右侧抽屉里的 Agent，用户在网页上向你提问。",
        *where,
        "规则：",
        "- 用 personal-assistant 的 MCP 工具查真实数据再回答，不要凭记忆或猜测。",
        "- 你现在只有读取权限，不能修改任何数据；用户要求修改时，告诉他在页面上怎么操作。",
        "- 用中文，简短直接，先给结论；列清单时每项一行。不要输出 YAML 或代码。",
        "- 回答里不要复述证件号、手机号等个人信息原文。",
        "",
        f"用户的问题：{question}",
    ])
