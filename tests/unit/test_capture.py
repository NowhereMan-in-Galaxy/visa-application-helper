"""spec 006 第三版：页面上填好的内容 → 存进基本信息（建议 + 勾选后写入）。基本信息是虚构的。"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
import config
from api.extension import EXTENSION_ORIGIN
from core.models import PersonalProfile
from core.profile_storage import load_personal_profile, save_personal_profile
from form_engine import capture, match

EXT = {"Host": "127.0.0.1:8000", "Origin": EXTENSION_ORIGIN}


@pytest.fixture(scope="module")
def d():
    return match.default_dictionary()


def F(i, kind, label, section=""):
    return {"i": i, "kind": kind, "label": label, "section": section, "name": "", "host": "online.immi.gov.au"}


# ImmiAccount 「Applicant」页的写法（2026-09-29 实测的标签和选项）
FIELDS = [
    F(0, "text", "Family name", "Passport details"),
    F(1, "select", "Nationality of passport holder", "Passport details"),
    F(2, "text", "Date of birth", "Passport details"),
    F(3, "select", "Relationship status", "Relationship status"),
    F(4, "radio", "Is this applicant currently, or have they ever been known by any other names?"),
    F(5, "text", "Town / City", "Place of birth"),
    F(6, "text", "Purpose of stay"),                      # 这次行程的内容：认不出，不存
    F(7, "radio", "Sex"),
]
VALUES = {"0": "EXAMPLE", "1": "CHINA - CHN", "2": "15 JUN 1990", "3": "Never Married",
          "4": "No", "5": "Sampletown", "6": "Tourism", "7": "Female"}


def test_empty_profile_gets_everything_recognised(d):
    items = {x["path"]: x for x in capture.suggest(FIELDS, VALUES, PersonalProfile(), d, "dd mmm yyyy")}
    assert items["identity.surname"]["value"] == "EXAMPLE" and items["identity.surname"]["before"] is None
    assert items["identity.nationality"]["value"] == "CHINA"               # 去掉后面的国家代码
    assert items["identity.date_of_birth"]["value"] == "1990-06-15"
    assert items["family.marital_status"]["value"] == "single"
    assert items["identity.sex"]["value"] == "female"
    assert items["identity.other_names"]["action"] == "none"               # 选了 No → 记为"没有"
    assert items["identity.birth_city"]["value"] == "Sampletown"
    assert len(items) == 7                                                 # 行程目的没有


def test_same_values_are_not_suggested(d):
    p = PersonalProfile.model_validate({
        "identity": {"surname": "Example", "nationality": "China", "date_of_birth": "1990-06-15", "sex": "female",
                     "birth_city": "SAMPLETOWN"},
        "family": {"marital_status": "single"}, "confirmed_none": ["identity.other_names"]})
    assert capture.suggest(FIELDS, VALUES, p, d, "dd mmm yyyy") == []
    changed = capture.suggest(FIELDS, {**VALUES, "5": "Othertown"}, p, d)
    assert [(x["path"], x["before"], x["after"]) for x in changed] == [("identity.birth_city", "SAMPLETOWN", "Othertown")]


@pytest.mark.parametrize("text, fmt, want", [
    ("2002-03-09", None, date(2002, 3, 9)),
    ("09 MAR 2002", None, date(2002, 3, 9)),
    ("Mar 9, 2002", None, date(2002, 3, 9)),
    ("09/03/2002", "dd/mm/yyyy", date(2002, 3, 9)),
    ("09/03/2002", None, None),                       # 不知道是日 / 月还是月 / 日，不猜
    ("31 FEB 2002", None, None),
])
def test_parse_date(text, fmt, want):
    assert capture.parse_date(text, fmt) == want


def test_to_changes_nests_paths():
    groups, none = capture.to_changes([
        {"path": "employment.current.address.city", "value": "Testville", "action": "set"},
        {"path": "employment.current.name", "value": "Example Co", "action": "set"},
        {"path": "identity.other_names", "action": "none"},
    ])
    assert groups == {"employment": {"current": {"address": {"city": "Testville"}, "name": "Example Co"}}}
    assert none == ["identity.other_names"]
    with pytest.raises(KeyError):
        capture.to_changes([{"path": "identity.no_such", "value": "x"}])


# ---- 接口 ----

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    save_personal_profile(tmp_path, PersonalProfile.model_validate(
        {"identity": {"surname": "EXAMPLE"}, "employment": {"current": {"name": "Example Co"}}}))
    return TestClient(app_module.app)


SCAN = ('{"v":1,"host":"online.immi.gov.au","sections":["Place of birth"],'
        '"f":[[0,"t","Family name",0,"","","",1,0],[1,"t","Town / City",0,"","","",1,0],[2,"t","Date of birth",0,"","","off",1,0]]}')


def test_capture_then_apply(client, tmp_path):
    r = client.post("/api/ext/capture", headers=EXT, json={"scan": SCAN, "values": {"0": "EXAMPLE", "1": "Sampletown", "2": "15 JUN 1990"}})
    assert r.status_code == 200
    items = r.json()["items"]
    assert {x["path"] for x in items} == {"identity.birth_city", "identity.date_of_birth"}
    assert load_personal_profile(tmp_path).identity.birth_city is None      # 只算建议，没写
    r = client.post("/api/ext/capture/apply", headers=EXT, json={"items": items + [
        {"path": "employment.current.address.city", "value": "Testville"}]})
    assert r.status_code == 200 and r.json() == {"saved": 3}
    p = load_personal_profile(tmp_path)
    assert p.identity.birth_city == "Sampletown" and p.identity.date_of_birth == date(1990, 6, 15)
    assert p.employment.current.name == "Example Co"                         # 同一个对象里别的字段没被冲掉
    assert p.employment.current.address.city == "Testville"


def test_apply_is_all_or_nothing(client, tmp_path):
    r = client.post("/api/ext/capture/apply", headers=EXT, json={"items": [
        {"path": "identity.birth_city", "value": "Sampletown"},
        {"path": "identity.date_of_birth", "value": "not a date"}]})
    assert r.status_code == 422
    assert load_personal_profile(tmp_path).identity.birth_city is None
    assert client.post("/api/ext/capture/apply", headers=EXT, json={"items": [{"path": "x.y", "value": 1}]}).status_code == 422
    assert client.post("/api/ext/capture/apply", headers=EXT, json={"items": []}).status_code == 422


def test_only_the_extension_can_write(client):
    for origin in ("https://online.immi.gov.au", "http://127.0.0.1:3000"):
        r = client.post("/api/ext/capture/apply", headers={**EXT, "Origin": origin},
                        json={"items": [{"path": "identity.birth_city", "value": "x"}]})
        assert r.status_code == 403
