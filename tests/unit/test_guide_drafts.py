"""spec 004 第 2 步：攻略类型、草稿、发布、词表别名、新建攻略任务。

共享区（community/）换成临时目录里的副本，材料根目录也是临时目录：测试绝不改动真实的攻略和词表。
"""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import api.app as app_module
from agent_runner import cli, jobs
from agent_tools import tools
from config import COMMUNITY_DIR
from core.material_types import load_vocabulary
from guide_fixtures import _BASE

LOCAL = {"Host": "127.0.0.1:8000"}


def draft_yaml(guide_id="uk-visitor-demo", **changes) -> str:
    g = copy.deepcopy(_BASE)
    g["id"] = guide_id
    g.update(changes)
    return yaml.safe_dump(g, allow_unicode=True, sort_keys=False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    community = tmp_path / "community"
    (community / "guides").mkdir(parents=True)
    shutil.copy(COMMUNITY_DIR / "material_types.yaml", community / "material_types.yaml")
    shutil.copytree(COMMUNITY_DIR / "forms", community / "forms")
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(app_module, "COMMUNITY_DIR", community)
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    real_before = (COMMUNITY_DIR / "material_types.yaml").read_text(encoding="utf-8")
    yield TestClient(app_module.app), community, root
    # 真实的共享区一个字都没变
    assert (COMMUNITY_DIR / "material_types.yaml").read_text(encoding="utf-8") == real_before
    assert not (COMMUNITY_DIR / "guides" / "uk-visitor-demo.yaml").exists()


def save(community, root, text, guide_id="uk-visitor-demo", suggestions=None):
    return tools.save_guide_draft(guide_id, text, suggestions, materials_root=root, community_dir=community)


# ---- 攻略类型 ----

def test_guide_types(env):
    c, _, _ = env
    types = {t["id"]: t for t in c.get("/api/guide-types", headers=LOCAL).json()}
    assert types["process"]["available"] is True
    assert types["travel"]["available"] is False


# ---- 验收 5：草稿只写草稿区 ----

def test_save_draft_writes_only_draft_area(env):
    _, community, root = env
    check = save(community, root, draft_yaml())
    assert check["valid"], check["errors"]
    assert (root / "drafts" / "process" / "uk-visitor-demo.yaml").is_file()
    assert list((community / "guides").iterdir()) == []


def test_draft_id_rules(env):
    _, community, root = env
    for bad in ("../evil", "Upper", "a/b", ""):
        with pytest.raises(ValueError):
            save(community, root, draft_yaml(), guide_id=bad)
    with pytest.raises(ValueError):  # 旅游攻略还不能建
        tools.save_guide_draft("x", draft_yaml("x"), guide_type="travel", materials_root=root, community_dir=community)


def test_invalid_draft_reports_errors(env):
    _, community, root = env
    check = save(community, root, draft_yaml(guide_id="other-id"))  # YAML 里的 id 和草稿 id 不一致
    assert not check["valid"] and any("文件名" in e for e in check["errors"])
    broken = save(community, root, "id: [unclosed")
    assert not broken["valid"] and "YAML" in broken["errors"][0]


def test_unresolved_names_and_suggestions(env):
    _, community, root = env
    g = yaml.safe_load(draft_yaml())
    g["requirements"].append({"id": "r-i20", "kind": "obtain", "raw_name": "I-20 表格",
                              "evidence": [{"source": "g1", "quote": "I20"}]})
    g["steps"][0]["requirements"].append("r-i20")
    check = save(community, root, yaml.safe_dump(g, allow_unicode=True),
                 suggestions=[{"raw_name": "I-20 表格", "key": "enrollment_certificate"},
                              {"raw_name": "乱写", "key": "no_such_key"}])
    assert {"requirement": "r-i20", "raw_name": "I-20 表格"} in check["unresolved"]
    assert [s["key"] for s in check["alias_suggestions"]] == ["enrollment_certificate"]  # 不存在的 key 被丢掉


# ---- 验收 6：发布 ----

def test_preview_and_publish(env):
    c, community, root = env
    save(community, root, draft_yaml())
    body = c.get("/api/guide-drafts/process/uk-visitor-demo", headers=LOCAL).json()
    assert body["check"]["valid"] and body["preview"]["steps"]
    assert [d["id"] for d in c.get("/api/guide-drafts", headers=LOCAL).json()] == ["uk-visitor-demo"]

    r = c.post("/api/guide-drafts/process/uk-visitor-demo/publish", headers=LOCAL)
    assert r.status_code == 200
    published = community / "guides" / "uk-visitor-demo.yaml"
    assert published.read_text(encoding="utf-8") == draft_yaml()
    assert not (root / "drafts" / "process" / "uk-visitor-demo.yaml").exists()


def test_publish_rejects_invalid_and_existing(env):
    c, community, root = env
    save(community, root, draft_yaml(guide_id="wrong"))
    assert c.post("/api/guide-drafts/process/uk-visitor-demo/publish", headers=LOCAL).status_code == 422
    assert list((community / "guides").iterdir()) == []

    save(community, root, draft_yaml())
    (community / "guides" / "uk-visitor-demo.yaml").write_text("已有", encoding="utf-8")
    assert c.post("/api/guide-drafts/process/uk-visitor-demo/publish", headers=LOCAL).status_code == 409
    assert (community / "guides" / "uk-visitor-demo.yaml").read_text(encoding="utf-8") == "已有"


def test_delete_draft(env):
    c, community, root = env
    save(community, root, draft_yaml())
    assert c.delete("/api/guide-drafts/process/uk-visitor-demo", headers=LOCAL).status_code == 200
    assert c.get("/api/guide-drafts/process/uk-visitor-demo", headers=LOCAL).status_code == 404


# ---- 验收 7：词表别名 ----

def test_add_alias_keeps_comments(env):
    c, community, _ = env
    path = community / "material_types.yaml"
    comments_before = [l for l in path.read_text(encoding="utf-8").splitlines() if l.lstrip().startswith("#")]
    r = c.post("/api/vocab/aliases", headers=LOCAL, json={"aliases": [{"key": "enrollment_certificate", "alias": "I-20: 表格"}]})
    assert r.status_code == 200
    text = path.read_text(encoding="utf-8")
    assert [l for l in text.splitlines() if l.lstrip().startswith("#")] == comments_before
    assert load_vocabulary(path).lookup("I-20: 表格") == "enrollment_certificate"


def test_alias_conflict_changes_nothing(env):
    c, community, _ = env
    path = community / "material_types.yaml"
    before = path.read_text(encoding="utf-8")
    # "身份证" 已经是 national_id 的别名，加到别的 key 会冲突；两条里有一条失败就全部不改
    r = c.post("/api/vocab/aliases", headers=LOCAL, json={"aliases": [
        {"key": "enrollment_certificate", "alias": "新叫法甲"}, {"key": "bank_statement", "alias": "身份证"}]})
    assert r.status_code == 422
    assert path.read_text(encoding="utf-8") == before
    assert c.post("/api/vocab/aliases", headers=LOCAL,
                  json={"aliases": [{"key": "no_such", "alias": "x"}]}).status_code == 422


def test_cross_site_writes_blocked(env):
    c, community, root = env
    save(community, root, draft_yaml())
    evil = {**LOCAL, "Origin": "https://evil.example"}
    assert c.post("/api/guide-drafts/process/uk-visitor-demo/publish", headers=evil).status_code == 403
    assert c.post("/api/vocab/aliases", headers=evil, json={"aliases": [{"key": "bank_statement", "alias": "x"}]}).status_code == 403
    assert c.delete("/api/guide-drafts/process/uk-visitor-demo", headers=evil).status_code == 403


# ---- 新建攻略任务 ----

def test_create_guide_command(fake_cli):
    cmd = cli.build_command("create_guide", "整理")
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "--chrome" in cmd
    assert cmd[cmd.index("--max-budget-usd") + 1] == "20"
    for forbidden in ("Write", "Edit", "Bash", "Read"):  # Read 只能以带路径的规则出现
        assert forbidden not in allowed
    assert all(not r.startswith("Read(") or r.startswith("Read(./") for r in allowed)
    assert not any("materials" in r for r in allowed)
    assert cli.MCP_PREFIX + "save_guide_draft" in allowed
    assert not any(r.endswith(("set_step_done", "update_personal_profile", "publish")) for r in allowed)


def test_create_guide_job_needs_available_type(fake_cli, env):
    c, _, _ = env
    for ctx in ({}, {"guide_type": "travel"}, {"guide_type": "nope"}):
        r = c.post("/api/agent/jobs", headers=LOCAL, json={"kind": "create_guide", "input": "x", "context": ctx})
        assert r.status_code == 422


def test_create_guide_job_prompts(fake_cli, env):
    c, _, _ = env
    r = c.post("/api/agent/jobs", headers=LOCAL, json={
        "kind": "create_guide", "input": "英签帖子 https://xhslink.cn/o/abc", "context": {"guide_type": "process"}})
    assert r.status_code == 200
    jobs.wait_finished(jobs.get(r.json()["job_id"]))
    argv = json.loads(fake_cli.read_text(encoding="utf-8"))
    assert "guide-author" in argv[1] and "xhs-reader" in argv[1] and "https://xhslink.cn/o/abc" in argv[1]
    # 接着同一次对话：只发简短提醒 + 用户的话
    r = c.post("/api/agent/jobs", headers=LOCAL, json={
        "kind": "create_guide", "input": "把第 3 步拆开", "session_id": "sess-1",
        "context": {"guide_type": "process", "draft_id": "uk-visitor-demo"}})
    jobs.wait_finished(jobs.get(r.json()["job_id"]))
    argv = json.loads(fake_cli.read_text(encoding="utf-8"))
    assert "把第 3 步拆开" in argv[1] and "uk-visitor-demo" in argv[1] and "--resume" in argv


def test_translate_emits_draft_event():
    state = {}
    jobs.translate({"type": "assistant", "message": {"content": [{
        "type": "tool_use", "id": "t1", "name": cli.MCP_PREFIX + "save_guide_draft",
        "input": {"guide_id": "uk-visitor", "yaml_text": "..."}}]}}, state)
    out = jobs.translate({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]}}, state)
    assert out == [("draft", {"draft_type": "process", "draft_id": "uk-visitor"})]
    nav = jobs.translate({"type": "assistant", "message": {"content": [{
        "type": "tool_use", "id": "t2", "name": "mcp__claude-in-chrome__navigate",
        "input": {"url": "https://www.xiaohongshu.com/explore/1?xsec_token=SECRET"}}]}}, {})
    assert nav[0][1]["text"] == "正在打开网页 www.xiaohongshu.com"  # 不显示分享参数
    early = jobs.translate({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {
        "type": "tool_use", "id": "t3", "name": cli.MCP_PREFIX + "save_guide_draft", "input": {}}}}, {})
    assert early and "写草稿" in early[0][1]["text"]
