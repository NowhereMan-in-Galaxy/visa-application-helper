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
}


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
