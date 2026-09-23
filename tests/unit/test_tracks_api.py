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


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """材料根目录和材料索引都换成临时目录，上传不会写进真实数据。"""
    root, index = tmp_path / "root", tmp_path / "index"
    (index / "records").mkdir(parents=True)
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    monkeypatch.setattr(app_module, "MATERIALS_INDEX_DIR", index)
    return TestClient(app_module.app), root, index


def test_upload_creates_record_and_confirms(isolated):
    c, root, index = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    v = c.post(f"/api/tracks/{tid}/requirements/r-insurance/upload",
               files={"file": ("policy.pdf", b"%PDF x", "application/pdf")}).json()
    r = next(q for q in v["requirements"] if q["id"] == "r-insurance")
    assert r["state"] == "ready"
    assert len(list((index / "records").glob("*.yaml"))) == 1
    assert list((root / "other").glob("*.pdf"))  # 保险不属于四大类，归到 other/


def test_upload_composite_needs_part(isolated):
    c, _, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    url = f"/api/tracks/{tid}/requirements/r-passport/upload"
    assert c.post(url, files={"file": ("a.pdf", b"x", "application/pdf")}).status_code == 422
    v = c.post(url, data={"part": "passport_bio_page"}, files={"file": ("a.pdf", b"x", "application/pdf")}).json()
    r = next(q for q in v["requirements"] if q["id"] == "r-passport")
    assert r["state"] == "missing" and {p["key"] for p in r["missing_parts"]} == {"passport_visa_page", "passport_stamped_pages"}


def test_export_endpoint(isolated):
    c, root, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    c.post(f"/api/tracks/{tid}/requirements/r-insurance/upload", files={"file": ("p.pdf", b"%PDF x", "application/pdf")})
    r = c.post(f"/api/tracks/{tid}/export").json()
    assert r["copied"] == ["01-旅行保险.pdf"]
    assert r["folder"].startswith(str(root / "exports"))


def test_track_summary_has_category_and_elapsed(client):
    c, _ = client
    c.post("/api/tracks", json={"guide": "schengen-tourist"})
    t = c.get("/api/tracks").json()[0]
    assert t["category"] == "签证" and t["elapsed_days"] == 0 and t["completed"] is None
