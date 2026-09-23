"""/api/guides 和 /api/tracks 的端到端流程。Track 写到临时目录，不碰真实的材料根目录。"""

import pytest
from fastapi.testclient import TestClient

import api.app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "get_materials_root", lambda: tmp_path)
    return TestClient(app_module.app), tmp_path


def test_guide_list_and_preview(client):
    c, _ = client
    guides = c.get("/api/guides").json()
    assert any(g["id"] == "schengen-tourist" and g["valid"] for g in guides)
    preview = c.get("/api/guides/schengen-tourist").json()["preview"]
    assert preview["next_step"] is not None


def test_unknown_guide_404(client):
    c, _ = client
    assert c.get("/api/guides/nope").status_code == 404
    assert c.post("/api/tracks", json={"guide": "nope"}).status_code == 404


def test_track_flow_persists(client):
    c, root = client
    created = c.post("/api/tracks", json={"guide": "schengen-tourist", "title": "测试办事"}).json()
    tid = created["id"]
    assert (root / "tracks" / f"{tid}.yaml").is_file()

    v = c.put(f"/api/tracks/{tid}/facts/identity", json={"value": "在职"}).json()
    states = {r["id"]: r["state"] for r in v["requirements"]}
    assert states["r-enrollment"] == "not_applicable"
    assert states["r-employment-letter"] != "not_applicable"

    c.put(f"/api/tracks/{tid}/steps/s-choose-country", json={"done": True})
    c.put(f"/api/tracks/{tid}/checks/c-hotel-itinerary", json={"done": True})
    again = c.get(f"/api/tracks/{tid}").json()  # 重新读文件，确认真的存下来了
    assert next(s for s in again["steps"] if s["id"] == "s-choose-country")["done"]
    assert next(k for k in again["checks"] if k["id"] == "c-hotel-itinerary")["done"]

    listed = c.get("/api/tracks").json()
    assert listed[0]["id"] == tid and listed[0]["title"] == "测试办事"


def test_invalid_fact_value_rejected(client):
    c, _ = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    assert c.put(f"/api/tracks/{tid}/facts/identity", json={"value": "宇航员"}).status_code == 422
    assert c.put(f"/api/tracks/{tid}/steps/s-nope", json={"done": True}).status_code == 404


def test_confirm_without_candidate_rejected(client):
    c, _ = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    # 旅行保险是材料库里不会有的东西，没有候选就不能"确认"
    assert c.put(f"/api/tracks/{tid}/matches/r-insurance", json={"confirmed": True}).status_code == 422
