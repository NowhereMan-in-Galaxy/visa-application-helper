"""删除一件办事：移到 tracks/.trash/，不真的删掉；首页的示例办事看完可以删。"""

import pytest
from fastapi.testclient import TestClient

import api.app as app_module

LOCAL = {"Host": "127.0.0.1:8000"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "get_materials_root", lambda: tmp_path)
    return TestClient(app_module.app), tmp_path


def test_delete_moves_to_trash(env):
    c, root = env
    t = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist", "title": "示例：申根短期旅游签证"}).json()
    r = c.delete(f"/api/tracks/{t['id']}", headers=LOCAL)
    assert r.status_code == 200 and r.json()["removed"] == t["id"]
    assert c.get("/api/tracks", headers=LOCAL).json() == []
    assert c.get(f"/api/tracks/{t['id']}", headers=LOCAL).status_code == 404
    trashed = list((root / "tracks" / ".trash").glob(f"{t['id']}-*.yaml"))
    assert len(trashed) == 1 and "示例" in trashed[0].read_text(encoding="utf-8")


def test_delete_unknown_and_cross_site(env):
    c, _ = env
    assert c.delete("/api/tracks/nope", headers=LOCAL).status_code == 404
    assert c.delete("/api/tracks/..x", headers=LOCAL).status_code == 404  # 不合法的 id 不会拼成别的路径
    assert c.delete("/api/tracks/..", headers=LOCAL).status_code in (404, 405)  # 路径被规范化，到不了删除接口
    t = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist"}).json()
    assert c.delete(f"/api/tracks/{t['id']}", headers={**LOCAL, "Origin": "https://evil.example"}).status_code == 403
    assert c.get(f"/api/tracks/{t['id']}", headers=LOCAL).status_code == 200


def test_same_id_can_be_created_again_after_delete(env):
    c, _ = env
    a = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist"}).json()
    c.delete(f"/api/tracks/{a['id']}", headers=LOCAL)
    b = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist"}).json()
    assert b["id"] == a["id"]  # 回收站里的不占用 id
