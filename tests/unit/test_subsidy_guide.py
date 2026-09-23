"""杭州应届生补贴攻略（community/guides/hangzhou-graduate-subsidies.yaml，试验 #3）：时间窗按原文规则算出。日期全部虚构。"""

from datetime import date

from fastapi.testclient import TestClient

import api.app as app_module
from config import COMMUNITY_DIR
from core.guides import load_guide
from core.material_types import load_vocabulary
from core.tracks import Track, compute_track_view

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root, index = tmp_path / "root", tmp_path / "index"
    (index / "records").mkdir(parents=True)
    monkeypatch.setattr(app_module, "get_materials_root", lambda: root)
    monkeypatch.setattr(app_module, "MATERIALS_INDEX_DIR", index)
    return TestClient(app_module.app), root, index


def step(v, sid):
    return next(s for s in v.steps if s.id == sid)


def test_repository_subsidy_guide():
    """仓库里的杭州补贴攻略：虚构的毕业/参保日期下，时间窗按原文规则算出。"""
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    g = load_guide(COMMUNITY_DIR / "guides" / "hangzhou-graduate-subsidies.yaml", vocab).guide
    t = Track(id="t", guide=g.id, title="t", created=date(2026, 7, 1),
              facts={"graduation_date": "2026-06-30", "first_insured": "2026-07-01",
                     "education": "本科", "full_time": "是", "own_house": "没有", "small_micro": "是"},
              done_steps=["s-first-insure", "s-talent-code"])
    v = compute_track_view(g, t, [], vocab, date(2026, 9, 23))
    assert step(v, "s-qinghe-1").window["state"] == "open"
    assert v.next_step == "s-qinghe-1"
    assert step(v, "s-living").window["opens"] == "2027-01-01"
    assert step(v, "s-living").window["closes"] == "2028-06-30"
    assert step(v, "s-employment").window["opens"] == "2027-07-01"
    assert step(v, "s-employment").window["closes"] == "2028-12-31"


def test_date_fact_and_calendar(isolated):
    c, root, _ = isolated
    tid = c.post("/api/tracks", json={"guide": "hangzhou-graduate-subsidies"}).json()["id"]
    assert c.put(f"/api/tracks/{tid}/facts/graduation_date", json={"value": "明年"}).status_code == 422
    c.put(f"/api/tracks/{tid}/facts/graduation_date", json={"value": "2099-06-30"})
    v = c.put(f"/api/tracks/{tid}/facts/first_insured", json={"value": "2099-07-01"}).json()
    assert {f["key"]: f["type"] for f in v["facts"]}["first_insured"] == "date"
    assert v["reminders"] and v["reminders"][0]["date"] <= v["reminders"][-1]["date"]

    v = c.put(f"/api/tracks/{tid}/steps/s-first-insure", json={"done": True}).json()
    saved = (root / "tracks" / f"{tid}.yaml").read_text(encoding="utf-8")
    assert "done_on:" in saved and "s-first-insure" in saved

    r = c.get(f"/api/tracks/{tid}/calendar.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.count("BEGIN:VEVENT") == len(v["reminders"])
