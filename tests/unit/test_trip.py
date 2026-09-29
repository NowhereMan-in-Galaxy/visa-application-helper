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
