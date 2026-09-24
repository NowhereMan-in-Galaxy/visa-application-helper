"""agent_tools.tools 的单元测试（spec 002 B2）。

Track 一律写到 tmp_path（通过 monkeypatch `config.get_materials_root`），不碰真实的材料根目录；
攻略读的是仓库里真实的 community/（共享区数据本来就不含个人信息，和 test_tracks_api.py 的做法一致）。
"""

from __future__ import annotations

from datetime import date

import pytest

import config
from agent_tools import tools
from core.guides import load_all_guides
from core.material_types import load_vocabulary
from core.tracks import TrackNotFoundError, create_track


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """材料根目录换成临时目录；材料索引仍然指向仓库里的真实目录（只读，B2 工具不写材料记录）。"""
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    return tmp_path


def _schengen_guide():
    vocab = load_vocabulary(config.COMMUNITY_DIR / "material_types.yaml")
    results = load_all_guides(config.COMMUNITY_DIR / "guides", vocab)
    return next(r.guide for r in results if r.path.stem == "schengen-tourist")


def _new_track(materials_root, **kwargs):
    return create_track(materials_root, _schengen_guide(), date.today(), **kwargs)


def test_list_guides_includes_schengen():
    guides = tools.list_guides()
    schengen = next(g for g in guides if g["id"] == "schengen-tourist")
    assert schengen["valid"] is True
    assert schengen["requirement_count"] > 0
    assert schengen["step_count"] > 0


def test_get_guide_returns_summary_and_preview():
    detail = tools.get_guide("schengen-tourist")
    assert detail["summary"]["id"] == "schengen-tourist"
    assert detail["preview"] is not None
    assert detail["preview"]["next_step"] is not None


def test_get_guide_unknown_raises():
    with pytest.raises(ValueError):
        tools.get_guide("does-not-exist")


def test_list_tracks_and_get_track(isolated):
    track = _new_track(isolated, title="测试办事")
    listed = tools.list_tracks()
    assert len(listed) == 1
    assert listed[0]["id"] == track.id
    assert listed[0]["title"] == "测试办事"
    assert listed[0]["category"] == "签证"
    assert listed[0]["error"] is None

    view = tools.get_track(track.id)
    assert view["id"] == track.id
    assert view["next_step"] is not None


def test_get_track_unknown_raises(isolated):
    with pytest.raises(TrackNotFoundError):
        tools.get_track("nope")


def test_set_fact_updates_requirements(isolated):
    track = _new_track(isolated)
    view = tools.set_fact(track.id, "identity", "在职")
    states = {r["id"]: r["state"] for r in view["requirements"]}
    assert states["r-enrollment"] == "not_applicable"
    assert states["r-employment-letter"] != "not_applicable"

    # 再读一遍确认真的写进了 tracks/*.yaml
    reloaded = tools.get_track(track.id)
    assert reloaded["facts"] == view["facts"]


def test_set_fact_illegal_value_raises(isolated):
    track = _new_track(isolated)
    with pytest.raises(ValueError):
        tools.set_fact(track.id, "identity", "宇航员")


def test_set_fact_unknown_track_raises(isolated):
    with pytest.raises(TrackNotFoundError):
        tools.set_fact("does-not-exist", "identity", "在职")


def test_set_step_done_persists_and_syncs_completion(isolated):
    track = _new_track(isolated)
    view = tools.set_step_done(track.id, "s-choose-country", True)
    assert next(s for s in view["steps"] if s["id"] == "s-choose-country")["done"] is True

    # 取消勾选也要生效
    view2 = tools.set_step_done(track.id, "s-choose-country", False)
    assert next(s for s in view2["steps"] if s["id"] == "s-choose-country")["done"] is False


def test_set_step_done_unknown_step_raises(isolated):
    track = _new_track(isolated)
    with pytest.raises(ValueError):
        tools.set_step_done(track.id, "s-nope", True)


def test_confirm_match_without_candidate_raises(isolated):
    track = _new_track(isolated)
    # 旅行保险材料库里不会有对应记录（tmp 材料索引是空的），没有候选就不能确认
    with pytest.raises(ValueError):
        tools.confirm_match(track.id, "r-insurance", True)


def test_confirm_match_unconfirm_is_noop_when_absent(isolated):
    track = _new_track(isolated)
    view = tools.confirm_match(track.id, "r-insurance", False)
    assert view["id"] == track.id


def test_validate_community_matches_cli_shape():
    result = tools.validate_community()
    assert result["vocabulary"]["valid"] is True
    schengen = next(g for g in result["guides"] if g["id"] == "schengen-tourist")
    assert schengen["valid"] is True
    assert isinstance(schengen["unresolved_types"], list)


# ---- 个人调整工具 ----

def test_mcp_adjustment_tools(monkeypatch, tmp_path):
    import config
    from agent_tools import tools
    from core.guides import load_guide  # noqa: F401  确保 core 可导入
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    from core.tracks import create_track
    from core.material_types import load_vocabulary
    from core.guides import load_all_guides
    vocab = load_vocabulary(config.COMMUNITY_DIR / "material_types.yaml")
    guide = next(r.guide for r in load_all_guides(config.COMMUNITY_DIR / "guides", vocab) if r.path.stem == "schengen-tourist")
    tid = create_track(tmp_path, guide, date(2026, 9, 23)).id
    v = tools.set_hidden(tid, "step", "s-insurance", True)
    assert any(h["id"] == "s-insurance" for h in v["hidden_items"])
    v = tools.set_note(tid, "requirement", "r-bank", "要盖章")
    assert next(r for r in v["requirements"] if r["id"] == "r-bank")["user_note"] == "要盖章"
    v = tools.add_custom_step(tid, "办存款证明", phase="p-materials")
    cs = next(s for s in v["steps"] if s["custom"])
    assert tools.set_step_done(tid, cs["id"], True)  # 自己加的步骤也能勾
    v = tools.add_custom_material(tid, "银行流水", cs["id"])
    assert next(r for r in v["requirements"] if r["custom"])["material_type"] == "bank_statement"
    v = tools.add_pitfall(tid, "流水要柜台打印")
    assert v["pitfalls"][0]["text"] == "流水要柜台打印"
    with pytest.raises(ValueError):
        tools.set_hidden(tid, "phase", "p-online", True)
