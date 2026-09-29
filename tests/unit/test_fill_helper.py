"""spec 005「对照清单」：基本信息 → 方便手动复制的一张表。基本信息全部是虚构的示例值。"""

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
from core.models import PersonalProfile
from core.profile_storage import save_personal_profile
from form_engine.match import default_dictionary
from form_engine.reference import reference

LOCAL = {"Host": "127.0.0.1:8000"}

PROFILE = PersonalProfile.model_validate({
    "identity": {"surname": "EXAMPLE", "sex": "female", "date_of_birth": "1990-06-05", "nationality": "中国",
                 "national_id_number": "000000199006050000"},
    "contact": {"home_address": {"city": "Testville"}, "mailing_same_as_home": True},
    "employment": {"primary_occupation": "not_employed",
                   "previous": [{"name": "Example Co", "start_date": "2015-01-02"}, {"name": "Sample Ltd"}]},
    "background": {"languages": ["Chinese", "English"]},
})


def items_by_path():
    r = reference(PROFILE, default_dictionary())
    return {it["path"]: it for g in r["groups"] for it in g["items"]}, r


def texts(item):
    return [v["text"] for v in item["values"]]


def test_only_filled_fields_grouped():
    items, r = items_by_path()
    assert [g["key"] for g in r["groups"]] == ["identity", "contact", "employment", "background"]
    assert "identity.given_names" not in items  # 空的不列
    assert items["contact.home_address.city"]["label"] == "家庭住址 › 城市"


def test_value_formats():
    items, _ = items_by_path()
    assert texts(items["identity.date_of_birth"]) == ["05/06/1990", "1990-06-05", "06/05/1990", "05 JUN 1990"]
    assert items["identity.date_of_birth"]["values"][0]["hint"] == "DD/MM/YYYY"
    assert texts(items["identity.nationality"]) == ["China", "中国"]
    assert items["identity.sex"]["values"] == [{"text": "Female", "hint": "女"}]
    assert items["employment.primary_occupation"]["values"][0]["text"] == "Not employed"
    assert texts(items["contact.mailing_same_as_home"]) == ["Yes"]


def test_lists_are_flattened():
    items, _ = items_by_path()
    assert texts(items["employment.previous.0.name"]) == ["Example Co"]
    assert items["employment.previous.1.name"]["label"] == "以前的工作 2 › 单位名称（英文）"
    assert texts(items["background.languages"]) == ["Chinese", "English"]


def test_sensitive_and_search_terms():
    items, _ = items_by_path()
    assert items["identity.national_id_number"]["sensitive"] is True
    assert items["identity.surname"]["sensitive"] is False
    assert "family name" in items["identity.surname"]["terms"]
    assert any("Surnames" in t for t in items["identity.surname"]["terms"])  # DS-160 提示也能搜


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "get_materials_root", lambda: tmp_path)
    return TestClient(app_module.app), tmp_path


def test_api(client):
    c, root = client
    assert c.get("/api/fill-helper", headers=LOCAL).json() == {"groups": []}
    save_personal_profile(root, PROFILE)
    body = c.get("/api/fill-helper", headers=LOCAL).json()
    assert body["groups"][0]["items"][0]["path"] == "identity.surname"
    assert c.get("/fill-helper.html", headers=LOCAL).status_code == 200
    assert c.get("/api/fill-helper", headers={"Host": "evil.example"}).status_code == 403
