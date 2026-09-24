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
    assert r["state"] == "missing" and [p["key"] for p in r["missing_parts"]] == ["passport_stamped_pages"]


def test_export_endpoint(isolated):
    c, root, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    c.post(f"/api/tracks/{tid}/requirements/r-insurance/upload", files={"file": ("p.pdf", b"%PDF x", "application/pdf")})
    r = c.post(f"/api/tracks/{tid}/export").json()
    assert r["copied"] == ["09-旅行保险.pdf"]  # 按攻略里原清单的编号命名
    assert r["folder"].startswith(str(root / "exports"))


def test_track_summary_has_category_and_elapsed(client):
    c, _ = client
    c.post("/api/tracks", json={"guide": "schengen-tourist"})
    t = c.get("/api/tracks").json()[0]
    assert t["category"] == "签证" and t["elapsed_days"] == 0 and t["completed"] is None


# ---- 倒排时间：PUT /api/tracks/{id}/deadline（spec 002 Phase C 第一条）----


def test_set_deadline_computes_latest_start(client):
    c, _ = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    v = c.put(f"/api/tracks/{tid}/deadline", json={"deadline": "2026-12-01"}).json()
    assert v["deadline"] == "2026-12-01"
    wait = next(s for s in v["steps"] if s["id"] == "s-wait")
    assert wait["latest_start"] == "2026-10-17"
    wait_phase = next(p for p in v["phases"] if p["id"] == "p-wait")
    assert wait_phase["latest_finish"] == "2026-12-01"


def test_clear_deadline_resets_to_null(client):
    c, _ = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    c.put(f"/api/tracks/{tid}/deadline", json={"deadline": "2026-12-01"})
    v = c.put(f"/api/tracks/{tid}/deadline", json={"deadline": None}).json()
    assert v["deadline"] is None
    assert all(s["latest_start"] is None for s in v["steps"])
    assert all(p["latest_finish"] is None for p in v["phases"])


def test_deadline_persists_after_reload(client):
    c, root = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    c.put(f"/api/tracks/{tid}/deadline", json={"deadline": "2026-12-01"})
    again = c.get(f"/api/tracks/{tid}").json()
    assert again["deadline"] == "2026-12-01"


def test_set_deadline_unknown_track_404(client):
    c, _ = client
    assert c.put("/api/tracks/nope/deadline", json={"deadline": "2026-12-01"}).status_code == 404



# ---- 手动从材料库挑选 ----

def _write_record(index, rid, type_, obtained="2026-09-01", **extra):
    import yaml
    data = {"id": rid, "category": "passport_scan", "type": type_, "obtained_date": obtained, **extra}
    (index / "records" / f"{rid}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_manual_pick_for_composite_and_learns_type(isolated):
    import yaml
    c, _, index = isolated
    _write_record(index, "bio", "护照个人信息页")
    _write_record(index, "scan", "护照扫描件（含签证页）")  # 词表认不出的叫法
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    url = f"/api/tracks/{tid}/matches/r-passport"
    assert c.put(url, json={"confirmed": True, "records": ["bio"]}).status_code == 422  # 组合材料要每部分一条
    v = c.put(url, json={"confirmed": True, "records": ["bio", "scan"]}).json()
    assert next(r for r in v["requirements"] if r["id"] == "r-passport")["state"] == "ready"
    learned = yaml.safe_load((index / "records" / "scan.yaml").read_text(encoding="utf-8"))
    assert learned["material_type"] == "passport_stamped_pages"  # 记住了，下次自动识别
    kept = yaml.safe_load((index / "records" / "bio.yaml").read_text(encoding="utf-8"))
    assert kept.get("material_type") is None  # 本来就认得的记录不改


def test_manual_pick_rejects_example_and_unknown(isolated):
    c, _, index = isolated
    _write_record(index, "example-photo", "证件照")
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    url = f"/api/tracks/{tid}/matches/r-photo"
    assert c.put(url, json={"confirmed": True, "records": ["example-photo"]}).status_code == 422
    assert c.put(url, json={"confirmed": True, "records": ["nope"]}).status_code == 404


# ---- 导出位置 ----

def test_export_to_chosen_folder_is_remembered(isolated, tmp_path):
    c, root, _ = isolated
    desk = tmp_path / "Desktop"
    desk.mkdir()
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    r = c.post(f"/api/tracks/{tid}/export", json={"dest": str(desk)}).json()
    assert r["folder"].startswith(str(desk.resolve()))
    assert c.get(f"/api/tracks/{tid}").json()["export_dir"] == str(desk)
    again = c.post(f"/api/tracks/{tid}/export").json()  # 不传 dest：沿用上次的位置
    assert again["folder"].startswith(str(desk.resolve()))


def test_export_refuses_repo_and_missing_folders(isolated):
    from config import REPO_ROOT
    c, _, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    assert c.post(f"/api/tracks/{tid}/export", json={"dest": str(REPO_ROOT / "community")}).status_code == 422
    assert c.post(f"/api/tracks/{tid}/export", json={"dest": "/definitely/not/here"}).status_code == 422
    assert c.post(f"/api/tracks/{tid}/export", json={"dest": "relative/path"}).status_code == 422


# ---- 步骤链接按回答过滤 ----

def test_links_follow_country_answer(isolated):
    c, _, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    step = lambda v: next(s for s in v["steps"] if s["id"] == "s-appointment")
    before = step(c.get(f"/api/tracks/{tid}").json())
    assert before["links"] and all(l["applies"] == "undecided" for l in before["links"])
    after = step(c.put(f"/api/tracks/{tid}/facts/country", json={"value": "法国"}).json())
    assert {l["title"] for l in after["links"]} == {"France-Visas 填申请表", "TLScontact 预约递签（进入后选 China）", "法国填表指南"}
    assert all(l["applies"] == "yes" for l in after["links"])
    # 官网链接带核实日期（2026-09-23 用浏览器核实过），填表指南是站内链接，不需要
    assert all(l["verified"] for l in after["links"] if l["kind"] == "official")


def test_form_guide_endpoint(client):
    c, _ = client
    f = c.get("/api/forms/france-visas").json()
    assert f["site"]["url"].startswith("https://") and f["sections"]
    assert c.get("/api/forms/nope").status_code == 404



# ---- 我的避坑点 ----

def test_pitfalls_add_toggle_edit_delete(client):
    c, _ = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    v = c.post(f"/api/tracks/{tid}/pitfalls", json={"text": "  流水别用网银截图  "}).json()
    item = v["pitfalls"][0]
    assert item["text"] == "流水别用网银截图" and item["done"] is False
    pid = item["id"]
    v = c.put(f"/api/tracks/{tid}/pitfalls/{pid}", json={"done": True}).json()
    assert v["pitfalls"][0]["done"] is True
    v = c.put(f"/api/tracks/{tid}/pitfalls/{pid}", json={"text": "流水要柜台打印盖章"}).json()
    assert v["pitfalls"][0]["text"] == "流水要柜台打印盖章"
    assert c.get(f"/api/tracks/{tid}").json()["pitfalls"][0]["done"] is True  # 确实存下来了
    assert c.delete(f"/api/tracks/{tid}/pitfalls/{pid}").json()["pitfalls"] == []
    assert c.delete(f"/api/tracks/{tid}/pitfalls/{pid}").status_code == 404


def test_pitfall_text_validation(client):
    c, _ = client
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    assert c.post(f"/api/tracks/{tid}/pitfalls", json={"text": "   "}).status_code == 422
    assert c.post(f"/api/tracks/{tid}/pitfalls", json={"text": "字" * 301}).status_code == 422


# ---- 个人调整接口 ----

def test_adjustment_endpoints_round_trip(isolated):
    c, _, index = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    base = f"/api/tracks/{tid}"
    v = c.put(f"{base}/hidden/steps/s-insurance", json={"hidden": True}).json()
    assert {"kind": "step", "id": "s-insurance", "title": "买申根旅行保险"} in v["hidden_items"]
    v = c.put(f"{base}/notes/requirements/r-bank", json={"note": "要柜台打印"}).json()
    assert next(r for r in v["requirements"] if r["id"] == "r-bank")["user_note"] == "要柜台打印"
    v = c.post(f"{base}/custom-steps", json={"title": "办存款证明", "phase": "p-materials"}).json()
    cs = next(s for s in v["steps"] if s["custom"])
    assert c.put(f"{base}/steps/{cs['id']}", json={"done": True}).status_code == 200  # 自己加的步骤也能勾
    v = c.post(f"{base}/custom-materials", json={"name": "邀请函", "step": cs["id"]}).json()
    cm = next(r for r in v["requirements"] if r["custom"])
    # 词表不认识的自己加的材料：上传后按名字建记录并直接确认
    v = c.post(f"{base}/requirements/{cm['id']}/upload", files={"file": ("inv.pdf", b"%PDF", "application/pdf")}).json()
    assert next(r for r in v["requirements"] if r["id"] == cm["id"])["state"] == "ready"
    v = c.delete(f"{base}/custom-steps/{cs['id']}").json()
    assert not any(s["custom"] for s in v["steps"])
    assert c.get(base).json()["hidden_items"]  # 其余调整仍然在


def test_adjustment_errors_are_422(isolated):
    c, _, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    assert c.put(f"/api/tracks/{tid}/hidden/steps/s-nope", json={"hidden": True}).status_code == 422
    assert c.post(f"/api/tracks/{tid}/custom-steps", json={"title": "  "}).status_code == 422
    assert c.delete(f"/api/tracks/{tid}/custom-steps/s-bank").status_code == 422


# ---- 长期资料 vs 本次专用（接口） ----

def test_upload_scope_defaults_and_override(isolated):
    import yaml
    c, _, index = isolated
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    pdf = lambda n: {"file": (n, b"%PDF", "application/pdf")}
    c.post(f"/api/tracks/{tid}/requirements/r-itinerary/upload", files=pdf("it.pdf"))       # 行程单：一次性
    c.post(f"/api/tracks/{tid}/requirements/r-id-card/upload", files=pdf("id.pdf"))         # 身份证：长期
    c.post(f"/api/tracks/{tid}/requirements/r-hotel/upload", data={"keep": "true"}, files=pdf("h.pdf"))  # 手动改为长期
    recs = {r["type"]: r for r in (yaml.safe_load(p.read_text(encoding="utf-8")) for p in (index / "records").glob("*.yaml"))}
    assert recs["行程单"]["for_track"] == tid
    assert recs["身份证"]["for_track"] is None
    assert recs["酒店预订单"]["for_track"] is None


def test_cannot_pick_other_tracks_one_off_and_convert_to_long_term(isolated):
    import yaml
    c, _, index = isolated
    (index / "records" / "inv.yaml").write_text(yaml.safe_dump({
        "id": "inv", "category": "other", "type": "行程单", "obtained_date": "2026-09-01", "for_track": "someone-else",
    }, allow_unicode=True), encoding="utf-8")
    tid = c.post("/api/tracks", json={"guide": "schengen-tourist"}).json()["id"]
    url = f"/api/tracks/{tid}/matches/r-itinerary"
    assert c.put(url, json={"confirmed": True, "records": ["inv"]}).status_code == 422
    assert c.patch("/api/materials/inv", json={"for_track": None}).json()["for_track"] is None  # 转为长期
    assert c.put(url, json={"confirmed": True, "records": ["inv"]}).status_code == 200
    assert c.patch("/api/materials/inv", json={"for_track": "no-such-track"}).status_code == 422



def test_upload_for_guide_requirement_unknown_to_vocabulary(isolated):
    """攻略里词表不认识的一次性材料（例如邀请函）也能上传：默认本次专用，并直接确认。"""
    import yaml
    c, _, index = isolated
    tid = c.post("/api/tracks", json={"guide": "australia-visitor-600-business"}).json()["id"]
    v = c.post(f"/api/tracks/{tid}/requirements/r-invitation/upload", files={"file": ("inv.pdf", b"%PDF", "application/pdf")}).json()
    assert next(r for r in v["requirements"] if r["id"] == "r-invitation")["state"] == "ready"
    rec = yaml.safe_load(next((index / "records").glob("*.yaml")).read_text(encoding="utf-8"))
    assert rec["type"] == "客户发的邀请函（英文）" and rec["for_track"] == tid
