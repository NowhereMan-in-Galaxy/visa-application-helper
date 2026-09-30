"""调起哪个 Agent CLI、带什么参数（spec 004"模块划分"）。

整个项目里只有这个文件知道具体用的是 Claude Code 的 `claude` 命令。以后要支持 API key 模式或别的 Agent，
只换这一层，页面和任务管理都不用改。

测试时用环境变量 `PA_AGENT_CLI` 指向一个假的 CLI 脚本，不会调用真的 Claude。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from config import REPO_ROOT

# MCP 服务在 .mcp.json 里的名字是 personal-assistant，Claude Code 给它的工具加的前缀是 mcp__<服务名>__
MCP_PREFIX = "mcp__personal-assistant__"

CHROME_PREFIX = "mcp__claude-in-chrome__"

# Read 只能读仓库里的规则、词表和攻略，读不到材料根目录里的个人文件（./ 表示相对仓库根目录）
READ_RULES = ["Read(./specs/**)", "Read(./community/**)", "Read(./docs/**)", "Read(./.claude/skills/**)"]

# 追问（kind="ask"）：读取 + 改自己的办事进度（每次都能在页面上撤销）+ 只能"提议"改基本信息（页面上确认才写）。
# 不给 update_personal_profile / confirm_personal_profile_none：那两个会直接写基本信息，只在终端里用。
ASK_TOOLS = READ_RULES + [
    MCP_PREFIX + name
    for name in (
        "list_guides",
        "get_guide",
        "list_tracks",
        "get_track",
        "get_personal_profile",
        "get_profile_gaps",
        "validate_community",
        # ② 改自己的办事进度（spec 004 第 3 步）
        "set_step_done",
        "set_fact",
        "set_hidden",
        "set_note",
        "add_pitfall",
        "add_custom_step",
        "add_custom_material",
        "confirm_match",
        # ③ 基本信息只能提议
        "propose_profile_update",
    )
]

# 新建 / 修改攻略（kind="create_guide"）：读规则 + 未登录浏览器读帖子 + 只能写草稿区。没有 Write / Edit / Bash。
CREATE_GUIDE_TOOLS = READ_RULES + ["Skill"] + [
    MCP_PREFIX + name
    for name in ("list_guides", "get_guide", "save_guide_draft", "get_guide_draft", "validate_guide_draft")
] + [
    CHROME_PREFIX + name
    for name in (
        "tabs_context_mcp", "tabs_create_mcp", "tabs_close_mcp", "navigate",
        "get_page_text", "javascript_tool", "computer", "find", "read_page",
    )
]

# 填表插件"让 Agent 补填"（kind="fill_assist"，spec 006 第二版）：只读基本信息、提议改基本信息、把"哪一格填什么"交给插件。
# 没有浏览器工具：Agent 碰不到官网，真正填写的是插件。
FILL_ASSIST_TOOLS = READ_RULES + [
    MCP_PREFIX + name
    # 读基本信息只给精简版 get_fill_reference：完整的 get_personal_profile 太长，Agent 读不完（2026-09-29 实测）
    for name in ("get_fill_reference", "get_profile_gaps", "get_track", "propose_profile_update",
                 "propose_trip_update", "submit_form_fills")
]

# 办事页「让 Agent 整理」（kind="trip_extract"，spec 007 第 2 步）：读用户说的话和勾选的这件事的材料，只能"提议"改行程信息。
# 唯一能读材料文件内容的任务；不给浏览器、不给写基本信息的工具。
TRIP_EXTRACT_TOOLS = READ_RULES + [
    MCP_PREFIX + name for name in ("get_track", "get_guide", "read_track_material", "propose_trip_update")
]

TOOLS_BY_KIND = {"ask": ASK_TOOLS, "create_guide": CREATE_GUIDE_TOOLS, "fill_assist": FILL_ASSIST_TOOLS,
                 "trip_extract": TRIP_EXTRACT_TOOLS}

# 用量上限（CLI 报告的折合美元；订阅用户不另收费，只是防止跑飞）。读帖子 + 看图 + 整理一份攻略比问答耗得多。
MAX_BUDGET_USD_BY_KIND = {"ask": 2.0, "create_guide": 20.0, "fill_assist": 2.0, "trip_extract": 3.0}
DEFAULT_MAX_BUDGET_USD = 5.0


def cli_name() -> str:
    return os.environ.get("PA_AGENT_CLI", "claude")


def find_cli() -> str | None:
    """返回 CLI 的完整路径；找不到返回 None。"""
    return shutil.which(cli_name())


def _run(args: list[str], timeout: float = 15) -> str | None:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def status() -> dict:
    """界面用来判断能不能用 Agent、用什么方式登录（spec 004"登录方式提示"）。

    `auth status` 的输出里还有邮箱、组织等信息，这里只取登录方式，其余一概不往外传。
    `ANTHROPIC_API_KEY` 只报告有没有设置，绝不读取它的值。
    """
    api_key_env = bool(os.environ.get("ANTHROPIC_API_KEY"))
    path = find_cli()
    if path is None:
        return {"available": False, "cli_path": None, "cli_version": None,
                "auth_method": None, "api_key_env": api_key_env}
    version = _run([path, "--version"])
    auth_method = None
    raw = _run([path, "auth", "status"])
    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = {}
        if info.get("loggedIn"):
            auth_method = info.get("authMethod") or "unknown"
        else:
            auth_method = "none"
    return {
        "available": version is not None,
        "cli_path": path,
        "cli_version": version,
        "auth_method": auth_method,
        "api_key_env": api_key_env,
    }


def build_command(kind: str, prompt: str, *, session_id: str | None = None,
                  max_budget_usd: float | None = None) -> list[str]:
    """拼出一次任务的完整命令行。

    - `-p`：问一句、答完就退出（非交互模式）
    - `stream-json` + `--include-partial-messages`：边干活边输出，页面才能实时显示
    - `--allowedTools`：白名单；`--permission-mode dontAsk`：白名单以外的工具直接拒绝，不会卡在"要不要允许"
    - `--mcp-config .mcp.json --strict-mcp-config`：只加载本项目的 MCP 服务
    - `--max-budget-usd`：用量上限，防止跑飞
    """
    if kind not in TOOLS_BY_KIND:
        raise ValueError(f"未知的任务类型：{kind}")
    path = find_cli()
    if path is None:
        raise FileNotFoundError(cli_name())
    if max_budget_usd is None:
        max_budget_usd = MAX_BUDGET_USD_BY_KIND.get(kind, DEFAULT_MAX_BUDGET_USD)
    cmd = [
        path, "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--allowedTools", ",".join(TOOLS_BY_KIND[kind]),
        "--permission-mode", "dontAsk",
        "--mcp-config", str(REPO_ROOT / ".mcp.json"), "--strict-mcp-config",
        "--max-budget-usd", f"{max_budget_usd:g}",
    ]
    if kind == "create_guide":
        cmd.append("--chrome")  # 读小红书帖子要用浏览器
    if session_id:
        cmd += ["--resume", session_id]
    return cmd
