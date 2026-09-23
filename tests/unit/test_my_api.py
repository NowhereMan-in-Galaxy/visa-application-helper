"""新版界面「02 我的资料」用到的三个新接口：
GET /api/material-types、GET /api/materials/usage、PATCH /api/materials/{id}。

材料根目录和材料索引都用临时目录，不碰真实数据（跟 tests/unit/test_tracks_api.py 的
`isolated` fixture一样的写法）。
"""

import pytest
from fastapi.testclient import TestClient

import api.app as app_module


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root, index = tmp_path / "root", tmp_path / "index"
    (index / "records").mkdir(parents=True)
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    monkeypatch.setattr(app_module, "MATERIALS_INDEX_DIR", index)
    return TestClient(app_module.app), root, index


# ---------- GET /api/material-types ----------


def test_material_types_lists_vocabulary(isolated):
    c, _, _ = isolated
    types = c.get("/api/material-types").json()
    keys = {t["key"] for t in types}
    assert "passport_bio_page" in keys
    entry = next(t for t in types if t["key"] == "passport_bio_page")
    assert entry["name"] == "护照个人信息页"
    assert entry["category"] == "passport_scan"


# ---------- GET /api/materials/usage ----------


def test_materials_usage_only_confirmed(isolated):
    c, _, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist", "title": "去法国"}).json()["id"]
    v = c.post(
        f"/api/tracks/{tid}/requirements/r-insurance/upload",
        files={"file": ("policy.pdf", b"%PDF x", "application/pdf")},
    ).json()
    req = next(r for r in v["requirements"] if r["id"] == "r-insurance")
    assert req["state"] == "ready"  # 上传后材料凑齐会自动确认
    record_id = req["records"][0]["id"]

    usage = c.get("/api/materials/usage").json()
    assert record_id in usage
    assert usage[record_id] == [
        {"track_id": tid, "track_title": "去法国", "requirement_name": usage[record_id][0]["requirement_name"]}
    ]
    assert usage[record_id][0]["requirement_name"]


def test_materials_usage_skips_unconfirmed_and_other_tracks(isolated):
    c, _, _ = isolated
    c.post("/api/tracks", json={"guide": "schengen-tourist"})  # 没有任何确认过的材料
    created = c.post(
        "/api/materials",
        data={"category": "other", "type": "旅行保险", "obtained_date": "2026-01-01"},
        files={"file": ("p.pdf", b"x", "application/pdf")},
    ).json()
    usage = c.get("/api/materials/usage").json()
    assert created["id"] not in usage


# ---------- PATCH /api/materials/{id} ----------


def test_patch_material_updates_and_keeps_unset_fields(isolated):
    c, _, _ = isolated
    created = c.post(
        "/api/materials",
        data={
            "category": "passport_scan",
            "type": "护照个人信息页",
            "obtained_date": "2020-01-01",
            "sublabel": "旧护照",
        },
    ).json()
    assert created["status"] == "已备齐" and created["days_until_expiry"] is None

    updated = c.patch(f"/api/materials/{created['id']}", json={"validity_days": 10}).json()
    # 没传 type / obtained_date / sublabel，保持原样；validity_days 生效后早就过期了
    assert updated["type"] == "护照个人信息页"
    assert updated["obtained_date"] == "2020-01-01"
    assert updated["sublabel"] == "旧护照"
    assert updated["status"] == "已过期"
    assert updated["days_until_expiry"] < 0


def test_patch_material_clears_optional_field_with_null(isolated):
    c, _, _ = isolated
    created = c.post(
        "/api/materials",
        data={"category": "passport_scan", "type": "护照个人信息页", "obtained_date": "2026-01-01", "sublabel": "旧护照"},
    ).json()
    updated = c.patch(f"/api/materials/{created['id']}", json={"sublabel": None}).json()
    assert updated["sublabel"] is None


def test_patch_material_rejects_empty_type(isolated):
    c, _, _ = isolated
    created = c.post(
        "/api/materials",
        data={"category": "passport_scan", "type": "护照个人信息页", "obtained_date": "2026-01-01"},
    ).json()
    assert c.patch(f"/api/materials/{created['id']}", json={"type": ""}).status_code == 422
    assert c.patch(f"/api/materials/{created['id']}", json={"type": "   "}).status_code == 422


def test_patch_material_not_found(isolated):
    c, _, _ = isolated
    assert c.patch("/api/materials/nope", json={"sublabel": "x"}).status_code == 404
