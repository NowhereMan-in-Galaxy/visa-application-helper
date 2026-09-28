"""spec 004 第 1 步：界面里的 Agent 的地基（调起 CLI、任务、事件流）。

全部用 tests/unit/fake_claude.py 代替真的 Claude Code，不联网、不花额度。
"""

import json

import pytest
from fastapi.testclient import TestClient

from agent_runner import cli, jobs
from api.app import app

LOCAL = {"Host": "127.0.0.1:8000"}
# fake_cli fixture 在 conftest.py 里


@pytest.fixture
def client():
    return TestClient(app)


def read_events(client, job_id):
    events = []
    with client.stream("GET", f"/api/agent/jobs/{job_id}/events", headers=LOCAL) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


# ---- 验收 1：检测 CLI 和登录方式 ----

def test_status_without_cli(monkeypatch, client):
    monkeypatch.setenv("PA_AGENT_CLI", "definitely-not-installed-cli-xyz")
    body = client.get("/api/agent/status", headers=LOCAL).json()
    assert body["available"] is False


def test_status_with_cli_hides_account_details(fake_cli, client):
    body = client.get("/api/agent/status", headers=LOCAL).json()
    assert body["available"] is True
    assert body["cli_version"].startswith("9.9.9")
    assert body["auth_method"] == "claude.ai"
    assert body["api_key_env"] is False
    assert "example.com" not in json.dumps(body)  # auth status 里的邮箱不能传到页面


def test_status_reports_api_key_without_value(fake_cli, monkeypatch, client):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value-123")
    body = client.get("/api/agent/status", headers=LOCAL).json()
    assert body["api_key_env"] is True
    assert "sk-secret-value-123" not in json.dumps(body)


# ---- 验收 2：命令行 ----

def test_ask_command_permissions(fake_cli):
    cmd = cli.build_command("ask", "你好", session_id="sess-9", max_budget_usd=3)
    assert cmd[1:3] == ["-p", "你好"]
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--max-budget-usd") + 1] == "3"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--resume") + 1] == "sess-9"
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    for forbidden in ("Write", "Edit", "Bash", "Read"):  # Read 只能以带路径的规则出现
        assert forbidden not in allowed
    # spec 004 第 3 步：可以改自己的办事进度（能撤销）、只能提议改基本信息
    assert cli.MCP_PREFIX + "set_step_done" in allowed
    assert cli.MCP_PREFIX + "propose_profile_update" in allowed
    for direct in ("update_personal_profile", "confirm_personal_profile_none", "save_guide_draft"):
        assert cli.MCP_PREFIX + direct not in allowed
    assert "--chrome" not in cmd


def test_unknown_kind_rejected(fake_cli):
    with pytest.raises(ValueError):
        cli.build_command("rm_everything", "x")


# ---- 验收 4：事件流 ----

def test_ask_streams_progress_text_and_done(fake_cli, client):
    r = client.post("/api/agent/jobs", headers=LOCAL, json={
        "kind": "ask", "input": "有几份攻略？", "context": {"page": "track", "track_id": "t1"}})
    assert r.status_code == 200
    events = read_events(client, r.json()["job_id"])
    types = [e["type"] for e in events]
    assert types[0] == "progress" and types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "text") == "一共有 6 份攻略。"  # 不重复
    assert any(e["type"] == "progress" and "查看攻略库" in e["text"] for e in events)
    assert events[-1]["session_id"] == "sess-1" and events[-1]["cost_usd"] == 0.25
    prompt = json.loads(fake_cli.read_text(encoding="utf-8"))[1]
    assert "t1" in prompt and "有几份攻略？" in prompt


def test_error_result_becomes_error_event(fake_cli, monkeypatch, client):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "error")
    job_id = client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "ask", "input": "x"}).json()["job_id"]
    events = read_events(client, job_id)
    assert events[-1]["type"] == "error" and "用量上限" in events[-1]["text"]


def test_crash_becomes_error_event(fake_cli, monkeypatch, client):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "crash")
    job_id = client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "ask", "input": "x"}).json()["job_id"]
    events = read_events(client, job_id)
    assert events[-1]["type"] == "error" and "boom" in events[-1]["text"]


# ---- 验收 3：一次一个任务、可以取消 ----

def test_second_job_conflicts_and_cancel_works(fake_cli, monkeypatch, client):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    job_id = client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "ask", "input": "x"}).json()["job_id"]
    r2 = client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "ask", "input": "y"})
    assert r2.status_code == 409
    assert client.post(f"/api/agent/jobs/{job_id}/cancel", headers=LOCAL).status_code == 200
    job = jobs.get(job_id)
    assert jobs.wait_finished(job, timeout=10)
    assert job.proc.poll() is not None  # 子进程确实退出了
    events = read_events(client, job_id)
    assert events[-1]["type"] == "error" and events[-1]["text"] == "已取消"


def test_input_validation(fake_cli, client):
    assert client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "ask", "input": "  "}).status_code == 422
    assert client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "create_guide", "input": "x"}).status_code == 422
    assert client.get("/api/agent/jobs/nope/events", headers=LOCAL).status_code == 404


def test_missing_cli_returns_503(monkeypatch, client):
    monkeypatch.setenv("PA_AGENT_CLI", "definitely-not-installed-cli-xyz")
    r = client.post("/api/agent/jobs", headers=LOCAL, json={"kind": "ask", "input": "x"})
    assert r.status_code == 503


# ---- 验收 10：跨站请求被挡 ----

def test_cross_site_post_blocked(fake_cli, client):
    r = client.post("/api/agent/jobs", json={"kind": "ask", "input": "x"},
                    headers={**LOCAL, "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert not jobs._jobs
