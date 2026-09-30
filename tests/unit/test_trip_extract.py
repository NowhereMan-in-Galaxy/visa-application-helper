"""spec 007 第 2 步：说几句话或读这件事的材料，让 Agent 整理成行程信息。数据都是虚构的。"""

import json
import zipfile

import pytest
import yaml
from fastapi.testclient import TestClient

import api.app as app_module
import config
from agent_runner import cli, jobs, prompts
from agent_tools import activity, tools
from core.trip import TRIP_GROUPS
from form_engine import match

LOCAL = {"Host": "127.0.0.1:8000"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "index" / "records").mkdir(parents=True)
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    monkeypatch.setattr(config, "get_materials_root", lambda: root)
    c = TestClient(app_module.app)
    tid = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist", "title": "示例"}).json()["id"]
    return c, root, tid


def record(root, rid, type_, file_ref, **extra):
    data = {"id": rid, "category": "other", "type": type_, "obtained_date": "2026-09-01", "file_ref": file_ref, **extra}
    (root / "index" / "records" / f"{rid}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def put_file(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---- 2a 新字段 ----

def test_new_fields_and_groups(env):
    c, _, tid = env
    v = c.get(f"/api/tracks/{tid}", headers=LOCAL).json()
    assert [g["key"] for g in v["trip_groups"]] == ["purpose", "dates", "transport", "itinerary", "stay", "host", "funding", "companions"]
    assert list(TRIP_GROUPS) == [g["key"] for g in v["trip_groups"]]
    r = c.put(f"/api/tracks/{tid}/trip", headers=LOCAL, json={
        "host_organization": "Example University", "arrival_flight": "XX123",
        "itinerary": [{"start_date": "2026-10-01", "end_date": "2026-10-05", "city": "Sampleville", "plan": "会议"}]})
    assert r.status_code == 200
    trip = r.json()["trip"]
    assert trip["itinerary"][0]["city"] == "Sampleville" and trip["host_organization"] == "Example University"
    assert c.put(f"/api/tracks/{tid}/trip", headers=LOCAL, json={"itinerary": [{"town": "x"}]}).status_code == 422


def test_engine_knows_flights_and_organisation():
    d = match.default_dictionary()
    fields = [{"i": 0, "kind": "text", "label": "Arrival flight number"},
              {"i": 1, "kind": "text", "label": "Return flight number"},
              {"i": 2, "kind": "text", "label": "Name of inviting organisation"},
              {"i": 3, "kind": "text", "label": "Name of contact person", "section": "Inviting organisation"},
              {"i": 4, "kind": "text", "label": "Organisation name", "section": "Inviting organisation"},
              {"i": 5, "kind": "text", "label": "Surname", "section": "Inviting person"}]
    from core.models import PersonalProfile
    r = match.plan(fields, PersonalProfile(), d)
    missing = {m["i"]: m["path"] for m in r["missing"]}
    assert missing[0] == "trip.arrival_flight" and missing[1] == "trip.departure_flight"
    assert missing[2] == "trip.host_organization" and missing[3] == "trip.host_name"
    assert missing[4] == "trip.host_organization"  # 不是"你的工作单位"
    assert 5 not in missing  # 邀请人的姓，不是你的姓


# ---- 2c 这件事的材料 ----

def test_trip_materials(env):
    c, root, tid = env
    record(root, "m-invite", "邀请函", "other/invite.pdf", for_track=tid)
    record(root, "m-other-track", "邀请函", "other/old.pdf", for_track="another-track")
    record(root, "m-photo", "照片", "other/photo.heic", for_track=tid)            # 不支持的格式
    record(root, "m-nofile", "邀请函", None, for_track=tid)
    record(root, "m-passport", "护照", "passport/p.jpg")                         # 长期材料，没确认挂在这件事上
    mats = c.get(f"/api/tracks/{tid}", headers=LOCAL).json()["trip_materials"]
    assert mats == [{"id": "m-invite", "type": "邀请函", "sublabel": None, "one_off": True}]
    # 确认挂在这件事上之后，长期材料也在，默认不勾
    track_file = root / "tracks" / f"{tid}.yaml"
    data = yaml.safe_load(track_file.read_text(encoding="utf-8"))
    data["matches"] = {"r-passport": ["m-passport"]}
    track_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    mats = {m["id"]: m for m in c.get(f"/api/tracks/{tid}", headers=LOCAL).json()["trip_materials"]}
    assert set(mats) == {"m-invite", "m-passport"} and mats["m-passport"]["one_off"] is False


# ---- 2d read_track_material ----

def docx_bytes(text):
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
                                        "<w:p><w:r><w:t>第二段 &amp; 结尾</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


def pdf_bytes(text):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    import io
    w = PdfWriter()
    page = w.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_read_track_material(env, monkeypatch):
    _, root, tid = env
    put_file(root, "other/invite.txt", "Invitation: Example University, 1-5 October 2026".encode())
    put_file(root, "other/hotel.docx", docx_bytes("Hotel Example, Sampleville"))
    put_file(root, "other/ticket.pdf", pdf_bytes("Flight XX123 arrives 2026-10-01 Sampleville"))
    record(root, "m-txt", "邀请函", "other/invite.txt", for_track=tid)
    record(root, "m-docx", "酒店预订单", "other/hotel.docx", for_track=tid)
    record(root, "m-pdf", "机票", "other/ticket.pdf", for_track=tid)
    record(root, "m-gone", "邀请函", "other/gone.pdf", for_track=tid)
    record(root, "m-escape", "邀请函", "../outside.txt", for_track=tid)
    record(root, "m-not-mine", "邀请函", "other/invite.txt", for_track="another-track")
    put_file(root.parent, "outside.txt", b"secret outside the materials root")

    monkeypatch.delenv(activity.KIND_ENV, raising=False)
    with pytest.raises(ValueError, match="只在"):
        tools.read_track_material(tid, "m-txt")
    monkeypatch.setenv(activity.KIND_ENV, "ask")
    with pytest.raises(ValueError, match="只在"):
        tools.read_track_material(tid, "m-txt")

    monkeypatch.setenv(activity.KIND_ENV, "trip_extract")
    assert "Example University" in tools.read_track_material(tid, "m-txt")["text"]
    docx = tools.read_track_material(tid, "m-docx")
    assert docx["type"] == "酒店预订单" and "Hotel Example" in docx["text"] and "第二段 & 结尾" in docx["text"]
    assert "XX123" in tools.read_track_material(tid, "m-pdf")["text"]
    with pytest.raises(ValueError, match="找不到"):
        tools.read_track_material(tid, "m-gone")
    with pytest.raises(ValueError, match="找不到"):
        tools.read_track_material(tid, "m-escape")
    with pytest.raises(ValueError, match="不是这件办事的材料"):
        tools.read_track_material(tid, "m-not-mine")


# ---- 2e 任务类型 trip_extract ----

def test_trip_extract_tools_are_narrow():
    assert set(cli.TRIP_EXTRACT_TOOLS) - set(cli.READ_RULES) == {
        cli.MCP_PREFIX + n for n in ("get_track", "get_guide", "read_track_material", "propose_trip_update")}
    for kind, allowed in cli.TOOLS_BY_KIND.items():
        if kind != "trip_extract":
            assert cli.MCP_PREFIX + "read_track_material" not in allowed


def test_trip_extract_job(env, fake_cli, monkeypatch, tmp_path):
    c, root, tid = env
    put_file(root, "other/invite.txt", b"Invitation")
    record(root, "m-txt", "邀请函", "other/invite.txt", for_track=tid)
    record(root, "m-not-mine", "邀请函", "other/invite.txt", for_track="another-track")
    kind_file = tmp_path / "kind.txt"
    monkeypatch.setenv("FAKE_CLAUDE_KIND", str(kind_file))

    def post(ctx):
        return c.post("/api/agent/jobs", headers=LOCAL, json={"kind": "trip_extract", "input": "10 月去开会", "context": ctx})
    assert post({}).status_code == 422
    assert post({"track_id": "no-such-track"}).status_code == 404
    assert post({"track_id": tid, "materials": ["m-not-mine"]}).status_code == 422
    assert post({"track_id": tid, "materials": ["m-txt"] * 7}).status_code == 422
    r = post({"track_id": tid, "materials": ["m-txt"]})
    assert r.status_code == 200
    jobs.wait_finished(jobs.get(r.json()["job_id"]))
    prompt = json.loads(fake_cli.read_text(encoding="utf-8"))[1]
    assert tid in prompt and "m-txt" in prompt and "propose_trip_update" in prompt and "10 月去开会" in prompt
    assert kind_file.read_text(encoding="utf-8") == "trip_extract"


def test_trip_extract_prompt_mentions_typical_items():
    p = prompts.trip_extract_prompt("x", {"track_id": "t1", "materials": []})
    assert "没有勾选材料" in p and "行程安排" in p and "邀请单位" in p
    follow = prompts.trip_extract_prompt("补充", {"track_id": "t1", "materials": ["m1"]}, follow_up=True)
    assert "补充" in follow and "m1" in follow


def test_trip_proposal_event_carries_track_id(env):
    _, root, tid = env
    state: dict = {}
    jobs.side_events(root, state)
    activity.propose_trip_update(root, tid, {"purpose": "Business"})
    (ev,) = [e for e in jobs.side_events(root, state) if e[0] == "proposal"]
    assert ev[1]["group"] == "trip" and ev[1]["track_id"] == tid


# ---- 第 3 步：开始清单 ----

def test_trip_sources_pick_trip_materials():
    from types import SimpleNamespace as R
    from core.trip import trip_source_ids
    reqs = [R(id="a", name="行程单", material_type="itinerary", state="missing"),
            R(id="b", name="房东邀请信（住朋友家）", material_type=None, state="missing"),
            R(id="c", name="Hotel booking", material_type=None, state="ready"),
            R(id="d", name="护照", material_type="passport", state="missing"),
            R(id="e", name="机票预订单", material_type="flight_reservation", state="not_applicable"),
            R(id="f", name="会议邀请函", material_type=None, state="undecided")]
    assert trip_source_ids(reqs) == ["a", "b", "c"]


def test_schengen_track_lists_trip_sources(env):
    c, _, tid = env
    v = c.get(f"/api/tracks/{tid}", headers=LOCAL).json()
    names = {r["id"]: r["name"] for r in v["requirements"]}
    assert {names[i] for i in v["trip_sources"]} >= {"行程单", "机票预订单", "酒店预订单"}
    assert "护照" not in {names[i] for i in v["trip_sources"]}


def test_trip_files_upload(env):
    c, root, tid = env
    url = f"/api/tracks/{tid}/trip-files"
    r = c.post(url, headers=LOCAL, data={"name": "会议邀请函"}, files={"file": ("invite.pdf", b"%PDF x", "application/pdf")})
    assert r.status_code == 200
    mats = r.json()["trip_materials"]
    assert [(m["type"], m["one_off"]) for m in mats] == [("会议邀请函", True)]
    (rec,) = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in (root / "index" / "records").glob("*.yaml")]
    assert rec["for_track"] == tid and rec["category"] == "other"
    assert (root / rec["file_ref"]).is_file()
    assert c.post(url, headers=LOCAL, data={"name": " "}, files={"file": ("a.pdf", b"x", "application/pdf")}).status_code == 422
    assert c.post(url, headers=LOCAL, data={"name": "x"}, files={"file": ("a.exe", b"x", "application/octet-stream")}).status_code == 422
    assert c.post("/api/tracks/no-such/trip-files", headers=LOCAL, data={"name": "x"},
                  files={"file": ("a.pdf", b"x", "application/pdf")}).status_code == 404
