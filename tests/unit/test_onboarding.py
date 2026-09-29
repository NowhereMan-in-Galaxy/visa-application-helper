"""「带我上手」：页面 Agent 按 .claude/skills/onboarding/SKILL.md 带新用户上手。"""

import re
from pathlib import Path

from agent_runner import cli, prompts

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "onboarding" / "SKILL.md"


def test_ask_prompt_points_to_onboarding_skill():
    p = prompts.ask_prompt("带我上手", {"page": "guides"})
    assert ".claude/skills/onboarding/SKILL.md" in p


def test_skill_exists_with_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert re.match(r"---\nname: onboarding\ndescription: .+\n---\n", text)


def test_ui_agent_may_use_the_tools_the_skill_needs():
    allowed = set(cli.ASK_TOOLS)
    for tool in ("list_tracks", "get_profile_gaps", "list_guides", "get_track", "propose_profile_update"):
        assert cli.MCP_PREFIX + tool in allowed, tool
    assert any(r.startswith("Read(./.claude/skills/") for r in allowed)
