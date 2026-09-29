"""spec 004 第 3 步：界面 Agent 改办事进度（可撤销）、提议改基本信息（确认才写）。

材料根目录是临时目录；基本信息里的电话是虚构的。
"""

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
import config
from agent_runner import jobs
from agent_tools import activity, tools
from core.models import PersonalProfile
from core.profile_storage import load_personal_profile, save_personal_profile

LOCAL = {"Host": "127.0.0.1:8000"}
EVIL = {**LOCAL, "Origin": "https://evil.example"}
FAKE_PHONE = "13800000000"


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    monkeypatch.setattr(config, "get_materials_root", lambda: root)
    monkeypatch.setenv(activity.UI_ENV, "1")
    c = TestClient(app_module.app)
    tid = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist", "title": "测试"}).json()["id"]
    return c, root, tid


def agent_ticks(root, tid, step="s-choose-country", done=True):
    """模拟网页调起的 Agent 调用 set_step_done（和 mcp_server 里的包装一样）。"""
    args = {"track_id": tid, "step_id": step, "done": done}
    return activity.record_track_write(
        root, "set_step_done", args, lambda: tools.set_step_done(tid, step, done, materials_root=root))


def step_done(c, tid, step="s-choose-country"):
    return next(s for s in c.get(f"/api/tracks/{tid}", headers=LOCAL).json()["steps"] if s["id"] == step)["done"]


# ---- 验收 8：② 类修改可以撤销 ----

def test_agent_write_is_logged_and_undoable(env):
    c, root, tid = env
    agent_ticks(root, tid)
    assert step_done(c, tid)
    [entry] = activity.read_activities(root)
    assert entry["summary"].startswith("已勾上：")
    r = c.post(f"/api/agent/undo/{entry['id']}", headers=LOCAL)
    assert r.status_code == 200
    assert not step_done(c, tid)
    assert c.post(f"/api/agent/undo/{entry['id']}", headers=LOCAL).status_code == 409  # 不能撤销两次


def test_undo_refused_after_later_change(env):
    c, root, tid = env
    agent_ticks(root, tid)
    entry_id = activity.read_activities(root)[0]["id"]
    c.put(f"/api/tracks/{tid}/facts/identity", headers=LOCAL, json={"value": "在职"})  # 用户之后又在页面上改了
    r = c.post(f"/api/agent/undo/{entry_id}", headers=LOCAL)
    assert r.status_code == 409 and "又改过" in r.json()["detail"]
    assert step_done(c, tid)  # 没有被冲掉


def test_no_log_outside_ui_and_no_log_without_change(env, monkeypatch):
    c, root, tid = env
    monkeypatch.delenv(activity.UI_ENV)
    agent_ticks(root, tid)
    assert activity.read_activities(root) == []  # 在终端里用时不记
    monkeypatch.setenv(activity.UI_ENV, "1")
    agent_ticks(root, tid)  # 已经是勾上的，文件没变
    assert activity.read_activities(root) == []


def test_undo_unknown_and_cross_site(env):
    c, root, tid = env
    assert c.post("/api/agent/undo/nope", headers=LOCAL).status_code == 404
    agent_ticks(root, tid)
    entry_id = activity.read_activities(root)[0]["id"]
    assert c.post(f"/api/agent/undo/{entry_id}", headers=EVIL).status_code == 403
    assert step_done(c, tid)


# ---- 验收 9：③ 类只提议，确认才写 ----

def test_proposal_confirm(env):
    c, root, _ = env
    res = activity.propose_profile_update(root, "contact", {"primary_phone": FAKE_PHONE})
    assert res["changed"][0]["label"] == "联系方式与住址 › 主要电话"
    assert load_personal_profile(root).contact.primary_phone is None  # 提议不写
    r = c.post(f"/api/agent/profile-proposals/{res['proposal_id']}/confirm", headers=LOCAL)
    assert r.status_code == 200
    assert load_personal_profile(root).contact.primary_phone == FAKE_PHONE
    assert activity.read_proposals(root) == []


def test_proposal_reject_and_invalid(env):
    c, root, _ = env
    res = activity.propose_profile_update(root, "contact", {"primary_phone": FAKE_PHONE})
    assert c.post(f"/api/agent/profile-proposals/{res['proposal_id']}/confirm", headers=EVIL).status_code == 403
    assert c.post(f"/api/agent/profile-proposals/{res['proposal_id']}/reject", headers=LOCAL).status_code == 200
    assert load_personal_profile(root).contact.primary_phone is None
    assert c.post(f"/api/agent/profile-proposals/{res['proposal_id']}/confirm", headers=LOCAL).status_code == 404
    with pytest.raises(KeyError):
        activity.propose_profile_update(root, "no_such_group", {"x": 1})
    with pytest.raises(Exception):
        activity.propose_profile_update(root, "contact", {"no_such_field": 1})
    assert activity.read_proposals(root) == []
    # 值没有变化时不记提议
    assert activity.propose_profile_update(root, "contact", {"primary_phone": None})["proposal_id"] is None


# ---- 页面事件：任务开始后新出现的修改 / 提议才报 ----

def test_side_events_only_new(env):
    _, root, tid = env
    agent_ticks(root, tid)  # 任务开始前就有的
    state = {}
    assert jobs.side_events(root, state) == []
    agent_ticks(root, tid, done=False)
    activity.propose_profile_update(root, "contact", {"primary_phone": FAKE_PHONE})
    events = jobs.side_events(root, state)
    assert [t for t, _ in events] == ["activity", "proposal"]
    assert events[0][1]["text"].startswith("已取消勾选：")
    assert events[1][1]["changed"][0]["after"] == FAKE_PHONE
    assert jobs.side_events(root, state) == []  # 不重复报


def test_proposal_lists_only_the_changed_cells(env):
    """2026-09-29 项目主：只改工作电话，确认卡片却把整个"目前的单位"对象当 JSON 列了出来。"""
    _, root, _ = env
    save_personal_profile(root, PersonalProfile.model_validate(
        {"employment": {"current": {"name": "Example Co", "address": {"city": "Testville"}}}}))
    res = activity.propose_profile_update(root, "employment", {"current": {"phone": FAKE_PHONE, "address": {"city": "Testville"}}})
    assert [(c["path"], c["before"], c["after"]) for c in res["changed"]] == [("employment.current.phone", None, FAKE_PHONE)]
    assert "电话" in res["changed"][0]["label"]
