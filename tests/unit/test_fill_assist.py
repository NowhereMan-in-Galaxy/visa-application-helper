"""spec 006 第二版：填表插件的"让 Agent 补填"（任务类型 fill_assist + MCP 工具 submit_form_fills）。"""

import json

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
import config
from agent_runner import cli, jobs, prompts
from agent_tools import activity

LOCAL = {"Host": "127.0.0.1:8000"}
FIELDS = [
    {"i": 7, "kind": "select", "label": "Purpose of Trip to the U.S.", "section": "Travel", "why": "没认出",
     "options": ["- SELECT ONE -", "TEMP. BUSINESS PLEASURE VISITOR (B)", "STUDENT (F)"]},
    {"i": 9, "kind": "textarea", "label": "Briefly describe your duties:", "section": "", "why": "没认出"},
]


# ---- submit_form_fills：记录 + 被后台任务报成 fills 事件 ----

def test_submit_records_and_side_events_report_once(tmp_path):
    state = {}
    assert jobs.side_events(tmp_path, state) == []  # 任务开始时的基线
    r = activity.submit_form_fills(tmp_path, [{"i": 7, "value": "TEMP. BUSINESS PLEASURE VISITOR (B)"}],
                                   [{"phrase": "describe your duties", "path": "employment.current.duties"}])
    assert r["count"] == 1 and r["learn"] == 1
    events = jobs.side_events(tmp_path, state)
    assert [t for t, _ in events] == ["fills"]
    assert events[0][1]["fills"] == [{"i": 7, "value": "TEMP. BUSINESS PLEASURE VISITOR (B)"}]
    assert events[0][1]["learn"][0]["path"] == "employment.current.duties"
    assert jobs.side_events(tmp_path, state) == []  # 不重复报


@pytest.mark.parametrize("fills, learn, msg", [
    ([], None, "不能为空"),
    ([{"i": "7", "value": "x"}], None, "非负整数"),
    ([{"i": True, "value": "x"}], None, "非负整数"),
    ([{"i": 1, "value": "  "}], None, "非空"),
    ([{"i": 1, "value": "x" * 2001}], None, "太长"),
    ([{"i": 1, "value": "x"}], [{"phrase": "p", "path": "identity.no_such"}], "不存在"),
])
def test_submit_rejects_bad_input(tmp_path, fills, learn, msg):
    with pytest.raises(ValueError, match=msg):
        activity.submit_form_fills(tmp_path, fills, learn)
    assert activity.read_form_fills(tmp_path) == []


# ---- 命令行权限：没有浏览器，只能读基本信息和交结果 ----

def test_fill_assist_command_has_no_browser(fake_cli):
    cmd = cli.build_command("fill_assist", "x")
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "--chrome" not in cmd
    assert not any(t.startswith(cli.CHROME_PREFIX) for t in allowed)
    assert cli.MCP_PREFIX + "submit_form_fills" in allowed
    assert cli.MCP_PREFIX + "get_personal_profile" in allowed
    for direct in ("update_personal_profile", "set_step_done", "save_guide_draft"):
        assert cli.MCP_PREFIX + direct not in allowed
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2"


# ---- 接口：格子清单的校验，prompt 里有编号、标签和选项 ----

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    return TestClient(app_module.app)


def test_jobs_endpoint_validates_fields(fake_cli, client):
    def post(ctx, session_id=None):
        return client.post("/api/agent/jobs", headers=LOCAL, json={
            "kind": "fill_assist", "input": "帮我补填", "context": ctx, "session_id": session_id})
    assert post({"host": "ceac.state.gov"}).status_code == 422
    assert post({"fields": [{"i": "x"}]}).status_code == 422
    assert post({"fields": [{"i": n} for n in range(61)]}).status_code == 422
    r = post({"host": "ceac.state.gov", "sensitive": False, "fields": FIELDS})
    assert r.status_code == 200
    jobs.wait_finished(jobs.get(r.json()["job_id"]))
    prompt = json.loads(fake_cli.read_text(encoding="utf-8"))[1]
    assert "#7 [select] Purpose of Trip to the U.S." in prompt
    assert "TEMP. BUSINESS PLEASURE VISITOR (B)" in prompt and "#9 [textarea]" in prompt
    assert "submit_form_fills" in prompt and "不要交" in prompt  # 没允许敏感字段


def test_prompt_follow_up_and_sensitive_flag():
    assert "用户允许填" in prompts.fill_assist_prompt("x", {"fields": FIELDS, "sensitive": True})
    follow = prompts.fill_assist_prompt("去旅游", {}, follow_up=True)
    assert "submit_form_fills" in follow and "去旅游" in follow


def test_mcp_tool_only_in_ui_jobs(monkeypatch, tmp_path):
    from agent_tools import mcp_server
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    monkeypatch.delenv(activity.UI_ENV, raising=False)
    with pytest.raises(ValueError, match="填表插件"):
        mcp_server.submit_form_fills([{"i": 1, "value": "x"}])
    monkeypatch.setenv(activity.UI_ENV, "1")
    assert mcp_server.submit_form_fills([{"i": 1, "value": "x"}])["count"] == 1
