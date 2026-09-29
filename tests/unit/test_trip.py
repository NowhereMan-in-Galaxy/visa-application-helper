"""spec 007 第 1 步：这次行程的信息，存在每件办事里。数据都是虚构的。"""

from datetime import date

import pytest
import yaml
from fastapi.testclient import TestClient

import api.app as app_module
from core.guides import validate_guide
from core.trip import TRIP_GROUPS, trip_group_keys

LOCAL = {"Host": "127.0.0.1:8000"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "get_materials_root", lambda: tmp_path)
    c = TestClient(app_module.app)
    t = c.post("/api/tracks", headers=LOCAL, json={"guide": "schengen-tourist", "title": "示例"}).json()
    return c, tmp_path, t


def test_new_track_asks_all_groups_for_visas(env):
    _, _, t = env
    assert [g["key"] for g in t["trip_groups"]] == list(TRIP_GROUPS)
    assert t["trip"]["purpose"] is None and t["trip"]["companions"] == []
    stay = next(g for g in t["trip_groups"] if g["key"] == "stay")
    assert [f["key"] for f in stay["fields"]] == ["stay_name", "stay_address", "stay_phone"]
    assert next(f for f in stay["fields"] if f["key"] == "stay_address")["type"] == "object"


def test_put_trip_merges_and_validates(env):
    c, root, t = env
    url = f"/api/tracks/{t['id']}/trip"
    r = c.put(url, headers=LOCAL, json={"purpose": "Tourism", "arrival_date": "2026-10-01",
                                        "stay_address": {"city": "Sampleville", "country": "France"}})
    assert r.status_code == 200
    r = c.put(url, headers=LOCAL, json={"stay_address": {"street": "1 Example Rd"}, "payer": "self",
                                        "companions": [{"name": "EXAMPLE A", "relationship": "朋友"}]})
    trip = r.json()["trip"]
    assert trip["purpose"] == "Tourism" and trip["arrival_date"] == "2026-10-01"
    assert trip["stay_address"] == {"street": "1 Example Rd", "city": "Sampleville", "province": None,
                                    "postal_code": None, "country": "France"}
    assert trip["companions"][0]["name"] == "EXAMPLE A"
    saved = yaml.safe_load((root / "tracks" / f"{t['id']}.yaml").read_text(encoding="utf-8"))
    assert saved["trip"]["purpose"] == "Tourism"
    before = (root / "tracks" / f"{t['id']}.yaml").read_text(encoding="utf-8")
    for bad in ({"nope": 1}, {"payer": "bank"}, {"arrival_date": "soon"}, {"stay_address": {"planet": "x"}}):
        assert c.put(url, headers=LOCAL, json=bad).status_code == 422, bad
    assert (root / "tracks" / f"{t['id']}.yaml").read_text(encoding="utf-8") == before
    assert c.put(url, headers={**LOCAL, "Origin": "https://evil.example"}, json={"purpose": "x"}).status_code == 403


def test_old_track_files_without_trip_still_load(env):
    c, root, t = env
    path = root / "tracks" / f"{t['id']}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.pop("trip", None)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert c.get(f"/api/tracks/{t['id']}", headers=LOCAL).json()["trip"]["purpose"] is None


def test_which_groups_a_guide_asks():
    assert trip_group_keys("签证", None) == list(TRIP_GROUPS)
    assert trip_group_keys("补贴", None) == []
    assert trip_group_keys("签证", ["purpose"]) == ["purpose"]
    assert trip_group_keys("签证", []) == []


def test_guide_trip_is_validated():
    from core.guides import Guide
    base = {"id": "x", "title": "X", "category": "签证", "sources": [], "requirements": [], "steps": []}
    assert not [e for e in validate_guide(Guide.model_validate({**base, "trip": ["purpose", "dates"]}), "x") if "trip" in e]
    errs = validate_guide(Guide.model_validate({**base, "trip": ["purpose", "nope", "purpose"]}), "x")
    assert any("nope" in e for e in errs) and any("重复" in e for e in errs)


# ---- 插件、对照清单、Agent：选了"这件事"就用它的行程信息 ----

from api.extension import EXTENSION_ORIGIN  # noqa: E402
from agent_runner import cli, prompts  # noqa: E402
from agent_tools import activity  # noqa: E402
import config  # noqa: E402

EXT = {**LOCAL, "Origin": EXTENSION_ORIGIN}
SCAN = ('{"v":1,"host":"visas-fr.tlscontact.com","sections":["Address where you will stay"],'
        '"f":[[0,"t","Purpose of your trip",0,"","","",0,0],[1,"t","City",0,"","","",0,0]]}')


@pytest.fixture
def filled(env, monkeypatch):
    c, root, t = env
    monkeypatch.setattr(config, "get_materials_root", lambda: root)
    c.put(f"/api/tracks/{t['id']}/trip", headers=LOCAL,
          json={"purpose": "Tourism", "stay_address": {"city": "Sampleville"}})
    return c, root, t


def test_extension_tracks_list_and_guess(filled):
    c, _, t = filled
    r = c.get("/api/ext/tracks", params={"host": "france-visas.gouv.fr"}, headers=EXT).json()
    assert r["tracks"] == [{"id": t["id"], "title": "示例"}]
    assert r["guess"] == t["id"]  # 申根攻略里有 france-visas.gouv.fr 的官网链接
    assert c.get("/api/ext/tracks", params={"host": "example.com"}, headers=EXT).json()["guess"] is None


def test_plan_uses_the_track(filled):
    c, _, t = filled
    without = c.post("/api/ext/plan", headers=EXT, json={"scan": SCAN}).json()
    assert {x["path"] for x in without["missing"]} == {"trip.purpose", "trip.stay_address.city"}
    with_track = c.post("/api/ext/plan", headers=EXT, json={"scan": SCAN, "track_id": t["id"]}).json()
    assert {o["i"]: o["v"] for o in with_track["ops"]} == {0: "Tourism", 1: "Sampleville"}
    assert c.post("/api/ext/plan", headers=EXT, json={"scan": SCAN, "track_id": "../x"}).status_code == 404


def test_capture_writes_trip_into_the_track(filled):
    c, root, t = filled
    values = {"0": "Business", "1": "Sampleville"}
    items = c.post("/api/ext/capture", headers=EXT, json={"scan": SCAN, "values": values, "track_id": t["id"]}).json()["items"]
    assert [(x["path"], x["before"], x["after"]) for x in items] == [("trip.purpose", "Tourism", "Business")]
    assert c.post("/api/ext/capture", headers=EXT, json={"scan": SCAN, "values": values}).json()["items"] == []
    assert c.post("/api/ext/capture/apply", headers=EXT, json={"items": items}).status_code == 422  # 没选这件事
    assert c.post("/api/ext/capture/apply", headers=EXT, json={"items": items, "track_id": t["id"]}).json() == {"saved": 1}
    saved = c.get(f"/api/tracks/{t['id']}", headers=LOCAL).json()["trip"]
    assert saved["purpose"] == "Business" and saved["stay_address"]["city"] == "Sampleville"


def test_fill_helper_has_a_trip_group(filled):
    c, _, t = filled
    groups = c.get("/api/fill-helper", params={"track_id": t["id"]}, headers=LOCAL).json()["groups"]
    assert groups[0]["key"] == "trip" and {i["path"] for i in groups[0]["items"]} == {"trip.purpose", "trip.stay_address.city"}
    assert all(g["key"] != "trip" for g in c.get("/api/fill-helper", headers=LOCAL).json()["groups"])
    assert c.get("/api/fill-helper", params={"track_id": "../x"}, headers=LOCAL).status_code == 404


def test_agent_proposes_trip_changes(filled):
    c, root, t = filled
    res = activity.propose_trip_update(root, t["id"], {"arrival_date": "2026-10-01", "purpose": "Tourism"})
    assert [(x["path"], x["after"]) for x in res["changed"]] == [("trip.arrival_date", "2026-10-01")]
    r = c.post(f"/api/agent/profile-proposals/{res['proposal_id']}/confirm", headers=LOCAL)
    assert r.status_code == 200
    assert c.get(f"/api/tracks/{t['id']}", headers=LOCAL).json()["trip"]["arrival_date"] == "2026-10-01"


def test_fill_assist_knows_the_track(fake_cli):
    allowed = cli.build_command("fill_assist", "x")
    allowed = allowed[allowed.index("--allowedTools") + 1].split(",")
    assert cli.MCP_PREFIX + "propose_trip_update" in allowed and cli.MCP_PREFIX + "get_track" in allowed
    p = prompts.fill_assist_prompt("x", {"fields": [], "track_id": "schengen-tourist-20260929"})
    assert 'get_fill_reference(track_id="schengen-tourist-20260929")' in p and "propose_trip_update" in p
    assert "没在插件里选" in prompts.fill_assist_prompt("x", {"fields": []})
