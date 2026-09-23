"""specs/003-personal-profile：「基本信息」（PersonalProfile 第二版）。

全部用虚构数据（张三 / ZHANG SAN / E12345678），材料根目录一律是 tmp_path，不碰真实文件。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import api.app as app_module
import config
from agent_tools import tools
from core.models import PROFILE_GROUPS, PersonalProfile, describe_personal_profile
from core.profile_storage import (
    PROFILE_FILENAME,
    ProfileFileError,
    load_personal_profile,
    save_personal_profile,
    save_profile_group,
)

SPEC = Path(__file__).resolve().parents[2] / "specs" / "003-personal-profile" / "spec.md"

LEGACY_YAML = """\
full_name: 张三
date_of_birth: '2000-01-01'
nationality: 中国
passport_number: E12345678
travel_history:
- country: 日本
  entry_date: '2026-05-01'
  exit_date: '2026-05-10'
  purpose: 旅游
"""


def _write(root: Path, text: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / PROFILE_FILENAME).write_text(text, encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    return TestClient(app_module.app), root


# ---------- 向后兼容：第一版平铺格式 ----------


def test_legacy_file_is_read_and_migrated(tmp_path):
    _write(tmp_path, LEGACY_YAML)
    p = load_personal_profile(tmp_path)
    assert p.identity.native_full_name == "张三"
    assert p.identity.date_of_birth == date(2000, 1, 1)
    assert p.identity.nationality == "中国"
    assert p.passport.passport_number == "E12345678"
    assert len(p.travel_history) == 1 and p.travel_history[0].country == "日本"
    # 旧名字作为只读别名还能读
    assert p.full_name == "张三" and p.passport_number == "E12345678"


def test_legacy_file_rewritten_in_new_format_on_save(tmp_path):
    _write(tmp_path, LEGACY_YAML)
    save_personal_profile(tmp_path, load_personal_profile(tmp_path))
    raw = yaml.safe_load((tmp_path / PROFILE_FILENAME).read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    for old in ("full_name", "date_of_birth", "nationality", "passport_number"):
        assert old not in raw
    assert raw["identity"]["native_full_name"] == "张三"
    assert raw["travel_history"][0]["entry_date"] == "2026-05-01"


def test_new_value_wins_over_legacy_value(tmp_path):
    _write(tmp_path, "full_name: 旧名字\nidentity:\n  native_full_name: 张三\n")
    assert load_personal_profile(tmp_path).identity.native_full_name == "张三"


def test_legacy_api_get_returns_grouped_shape(client):
    c, root = client
    _write(root, LEGACY_YAML)
    body = c.get("/api/personal-profile").json()
    assert body["identity"]["native_full_name"] == "张三"
    assert body["passport"]["passport_number"] == "E12345678"
    assert body["travel_history"][0]["country"] == "日本"


def test_missing_file_gives_empty_profile(tmp_path):
    p = load_personal_profile(tmp_path)
    assert p.education.schools == [] and p.identity.surname is None


# ---------- 拼错的字段 / 坏文件 ----------


def test_typo_field_in_file_raises_clear_error(tmp_path):
    _write(tmp_path, "identity:\n  surnme: ZHANG\n")
    with pytest.raises(ProfileFileError):
        load_personal_profile(tmp_path)


def test_broken_file_returns_500_with_detail_and_is_not_overwritten(client):
    c, root = client
    _write(root, "identity:\n  surnme: ZHANG\n")
    r = c.get("/api/personal-profile")
    assert r.status_code == 500 and PROFILE_FILENAME in r.json()["detail"]
    r = c.put("/api/personal-profile/identity", json={"surname": "ZHANG"})
    assert r.status_code == 500
    assert "surnme" in (root / PROFILE_FILENAME).read_text(encoding="utf-8")


def test_typo_field_in_request_is_rejected(client):
    c, _ = client
    r = c.put("/api/personal-profile/identity", json={"surnme": "ZHANG"})
    assert r.status_code == 422
    assert "surnme" in r.json()["detail"]


# ---------- 按分组保存往返 ----------

EDUCATION = {
    "schools": [
        {
            "name": "EXAMPLE UNIVERSITY",
            "name_native": "示例大学",
            "address": {"street": "1 EXAMPLE ROAD", "city": "EXAMPLE CITY", "province": None,
                        "postal_code": "100000", "country": "中国"},
            "course_of_study": "COMPUTER SCIENCE",
            "degree": "本科 学士",
            "start_date": "2018-09-01",
            "end_date": "2022-07-01",
        }
    ]
}


def test_group_save_round_trip_via_api(client):
    c, _ = client
    r = c.put("/api/personal-profile/identity", json={"surname": "ZHANG", "given_names": "SAN",
                                                      "native_full_name": "张三", "sex": "male",
                                                      "date_of_birth": "2000-01-01",
                                                      "other_names": [{"surname": "LI", "given_names": "SI"}]})
    assert r.status_code == 200, r.text
    r = c.put("/api/personal-profile/education", json=EDUCATION)
    assert r.status_code == 200, r.text
    body = c.get("/api/personal-profile").json()
    assert body["identity"]["surname"] == "ZHANG"
    assert body["identity"]["other_names"] == [{"surname": "LI", "given_names": "SI"}]
    assert body["education"] == EDUCATION


def test_group_save_keeps_other_groups_and_travel_history(tmp_path):
    _write(tmp_path, LEGACY_YAML)
    save_profile_group(tmp_path, "contact", {"email": "zhangsan@example.com", "other_emails": ["a@example.com"]})
    p = load_personal_profile(tmp_path)
    assert p.contact.email == "zhangsan@example.com"
    assert p.identity.native_full_name == "张三"
    assert len(p.travel_history) == 1


def test_list_items_add_and_remove_by_resaving_group(client):
    c, _ = client
    two = {"accounts": [{"platform": "微博", "identifier": "zhangsan_x"}, {"platform": "LinkedIn", "identifier": "zhang-san"}]}
    assert c.put("/api/personal-profile/social_media", json=two).status_code == 200
    one = {"accounts": [{"platform": "LinkedIn", "identifier": "zhang-san"}]}
    body = c.put("/api/personal-profile/social_media", json=one).json()
    assert body["social_media"]["accounts"] == one["accounts"]
    assert body["social_media"]["other_platforms"] == []


def test_unknown_group_is_404(client):
    c, _ = client
    assert c.put("/api/personal-profile/travel_history", json={}).status_code == 404
    assert c.put("/api/personal-profile/nope", json={}).status_code == 404


def test_existing_travel_history_endpoints_still_work(client):
    c, _ = client
    c.put("/api/personal-profile/identity", json={"surname": "ZHANG"})
    r = c.post("/api/personal-profile/travel-history", json={"country": "日本", "entry_date": "2026-05-01"})
    assert r.status_code == 200
    body = c.get("/api/personal-profile").json()
    assert body["identity"]["surname"] == "ZHANG" and len(body["travel_history"]) == 1


# ---------- 非法值 ----------


@pytest.mark.parametrize("value", ["2000-13-01", "2000-02-30", "not-a-date", "2000/01/01x"])
def test_invalid_date_rejected(client, value):
    c, root = client
    r = c.put("/api/personal-profile/identity", json={"date_of_birth": value})
    assert r.status_code == 422
    assert "date_of_birth" in r.json()["detail"]
    assert not (root / PROFILE_FILENAME).exists()


def test_invalid_date_inside_list_item_rejected(client):
    c, _ = client
    bad = {"schools": [{"name": "X", "start_date": "2018-02-31"}]}
    r = c.put("/api/personal-profile/education", json=bad)
    assert r.status_code == 422 and "schools.0.start_date" in r.json()["detail"]


def test_invalid_select_value_rejected(client):
    c, _ = client
    assert c.put("/api/personal-profile/family", json={"marital_status": "maybe"}).status_code == 422


# ---------- 字段说明 ----------


def test_fields_endpoint_lists_all_groups(client):
    c, _ = client
    groups = c.get("/api/personal-profile/fields").json()
    assert [g["key"] for g in groups] == list(PROFILE_GROUPS)
    identity = {f["key"]: f for f in groups[0]["fields"]}
    assert identity["date_of_birth"]["type"] == "date" and identity["date_of_birth"]["sensitive"] is True
    assert identity["surname"]["ds160"].startswith("Personal 1")
    assert identity["sex"]["type"] == "select"
    assert identity["other_names"]["type"] == "list"


def _all_keys(fields):
    for f in fields:
        yield f["key"]
        yield from _all_keys(f.get("fields", []))
        yield from _all_keys(f.get("item_fields", []))


def test_every_field_key_is_documented_in_spec():
    """spec 的字段表和代码不能各说各话：代码里每个字段 key 都要在 spec 里以 `key` 形式出现。"""
    text = SPEC.read_text(encoding="utf-8")
    documented = set(re.findall(r"`([a-z0-9_]+)`", text))
    missing = set()
    for g in describe_personal_profile():
        missing |= {k for k in [g["key"], *_all_keys(g["fields"])] if k not in documented}
    assert not missing, f"spec 里缺少这些字段：{sorted(missing)}"


def test_every_field_has_chinese_label():
    for g in describe_personal_profile():
        for f in g["fields"]:
            assert re.search(r"[一-鿿]", f["label"]), f["key"]


# ---------- MCP 只读工具 ----------


def test_mcp_get_personal_profile_returns_profile_and_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    _write(tmp_path, LEGACY_YAML)
    save_profile_group(tmp_path, "passport", {"passport_number": "E12345678", "expiry_date": "2030-01-01"})
    result = tools.get_personal_profile()
    assert result["profile"]["identity"]["native_full_name"] == "张三"
    assert result["profile"]["passport"]["expiry_date"] == "2030-01-01"
    assert result["profile"]["travel_history"][0]["country"] == "日本"
    passport_fields = next(g for g in result["fields"] if g["key"] == "passport")["fields"]
    number = next(f for f in passport_fields if f["key"] == "passport_number")
    assert number["sensitive"] is True and "Passport" in number["ds160"]


def test_mcp_server_registers_only_read_tool_for_profile():
    from agent_tools import mcp_server

    src = Path(mcp_server.__file__).read_text(encoding="utf-8")
    assert "def get_personal_profile" in src
    assert not re.search(r"def (set|save|update|put)_personal_profile", src)
    assert not re.search(r"def (set|save|update)_profile", src)


def test_constructor_accepts_legacy_kwargs():
    p = PersonalProfile(full_name="张三", passport_number="E12345678")
    assert p.identity.native_full_name == "张三" and p.passport.passport_number == "E12345678"
