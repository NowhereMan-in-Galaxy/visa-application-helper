"""specs/002 数据结构 §1：攻略校验规则。每条规则至少一个"违规被拒绝"的用例。"""

import pytest
from pydantic import ValidationError

from config import COMMUNITY_DIR
from core.guides import Guide, load_all_guides, load_guide, validate_guide
from core.material_types import load_vocabulary

from guide_fixtures import VOCAB, guide_dict


def errors_for(data: dict, file_stem: str | None = "demo-guide") -> list[str]:
    return validate_guide(Guide.model_validate(data), VOCAB, file_stem=file_stem)


def assert_rejected(data: dict, fragment: str, file_stem: str | None = "demo-guide") -> None:
    errors = errors_for(data, file_stem)
    assert any(fragment in e for e in errors), errors


def test_base_fixture_is_valid():
    assert errors_for(guide_dict()) == []


def test_id_must_match_file_name():
    assert_rejected(guide_dict(), "必须与文件名", file_stem="other-name")


def test_id_format():
    d = guide_dict(); d["id"] = "Demo_Guide"
    assert_rejected(d, "只能包含小写字母", file_stem=None)


def test_category_must_be_known():
    d = guide_dict(); d["category"] = "旅游"
    assert_rejected(d, "category")


def test_duplicate_ids():
    d = guide_dict(); d["requirements"].append(dict(d["requirements"][0]))
    assert_rejected(d, "id 重复")


def test_step_references_unknown_requirement():
    d = guide_dict(); d["steps"][0]["requirements"].append("r-nope")
    assert_rejected(d, "不存在的 requirement r-nope")


def test_depends_on_unknown_step():
    d = guide_dict(); d["steps"][0]["depends_on"] = ["s-nope"]
    assert_rejected(d, "不存在的 step s-nope")


def test_check_references_unknown_requirement():
    d = guide_dict(); d["checks"][0]["involves"] = ["r-nope"]
    assert_rejected(d, "involves 引用了不存在的 requirement")


def test_evidence_references_unknown_source():
    d = guide_dict(); d["requirements"][0]["evidence"] = [{"source": "g9", "quote": "x"}]
    assert_rejected(d, "不存在的 source g9")


def test_conflict_references_unknown_source():
    d = guide_dict(); d["conflicts"] = [{"id": "k1", "about": "r-bank", "claims": [{"source": "g9", "quote": "x"}]}]
    assert_rejected(d, "conflict k1")


def test_dependency_cycle():
    d = guide_dict(); d["steps"][0]["depends_on"] = ["s-submit"]
    assert_rejected(d, "成环")


def test_requirement_must_be_attached_to_a_step():
    d = guide_dict(); d["steps"][0]["requirements"] = ["r-bank"]  # r-extra 不再挂在任何步骤上
    assert_rejected(d, "r-extra：没有挂在任何 step 上")


def test_evidence_required():
    d = guide_dict(); d["steps"][0]["evidence"] = []
    assert_rejected(d, "至少需要一条 evidence")


def test_quote_length_limit():
    d = guide_dict(); d["requirements"][0]["evidence"] = [{"source": "g1", "quote": "字" * 61}]
    assert_rejected(d, "超过 60 字")


def test_kind_must_be_known():
    d = guide_dict(); d["requirements"][0]["kind"] = "buy"
    with pytest.raises(ValidationError):
        Guide.model_validate(d)


def test_unknown_field_rejected():
    d = guide_dict(); d["requirements"][0]["matched_records"] = []  # 个人状态字段不能出现在共享攻略里
    with pytest.raises(ValidationError):
        Guide.model_validate(d)


def test_material_type_must_be_in_vocabulary():
    d = guide_dict(); d["requirements"][0]["material_type"] = "unknown_type"
    assert_rejected(d, "不在词表里")


def test_raw_name_required_without_material_type():
    d = guide_dict(); d["requirements"][3]["raw_name"] = " "
    assert_rejected(d, "raw_name 必填")


def test_condition_unknown_fact():
    d = guide_dict(); d["requirements"][1]["applies_if"] = [{"fact": "age", "in": ["18"]}]
    assert_rejected(d, "不存在的 fact age")


def test_condition_value_not_in_options():
    d = guide_dict(); d["requirements"][1]["applies_if"] = [{"fact": "identity", "in": ["退休"]}]
    assert_rejected(d, "不在 fact identity 的选项")


def test_ask_if_cannot_reference_itself():
    d = guide_dict(); d["facts"]["same_hukou"]["ask_if"] = [{"fact": "same_hukou", "in": ["是"]}]
    assert_rejected(d, "不能引用自己")


def test_duration_days_order():
    d = guide_dict(); d["steps"][3]["duration_days"] = {"typical": 30, "max": 20}
    assert_rejected(d, "duration_days")


def test_source_url_scheme():
    d = guide_dict(); d["sources"][0]["url"] = "javascript:alert(1)"
    assert_rejected(d, "http:// 或 https://")


def test_broken_yaml_is_reported_not_raised(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("id: [unclosed", encoding="utf-8")
    result = load_guide(path, VOCAB)
    assert not result.valid and "YAML" in result.errors[0]


def test_repository_guides_are_valid():
    """仓库里所有共享攻略都必须通过校验。"""
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    results = load_all_guides(COMMUNITY_DIR / "guides", vocab)
    assert results, "community/guides 里至少应有一份攻略"
    for r in results:
        assert r.valid, f"{r.path.name}: {r.errors}"


# ---- 阶段（phases） ----

def with_phases() -> dict:
    d = guide_dict()
    d["phases"] = [{"id": "p-prep", "title": "准备"}, {"id": "p-go", "title": "递交", "mode": "offline"}]
    for s in d["steps"]:
        s["phase"] = "p-go" if s["id"] == "s-submit" else "p-prep"
    return d


def test_phases_valid():
    assert errors_for(with_phases()) == []


def test_step_must_have_phase_when_phases_defined():
    d = with_phases(); del d["steps"][0]["phase"]
    assert_rejected(d, "每个步骤都必须写 phase")


def test_step_phase_must_exist():
    d = with_phases(); d["steps"][0]["phase"] = "p-nope"
    assert_rejected(d, "不存在的阶段 p-nope")


def test_phase_without_steps_rejected():
    d = with_phases(); d["phases"].append({"id": "p-empty", "title": "空阶段"})
    assert_rejected(d, "p-empty：没有任何步骤")


def test_phase_mode_must_be_known():
    d = with_phases(); d["phases"][0]["mode"] = "mail"
    with pytest.raises(ValidationError):
        Guide.model_validate(d)



# ---- 链接与导出命名 ----

def test_link_needs_exactly_one_of_url_and_form():
    d = guide_dict(); d["steps"][0]["links"] = [{"title": "x"}]
    assert_rejected(d, "url 和 form 必须二选一")


def test_link_url_scheme():
    d = guide_dict(); d["steps"][0]["links"] = [{"title": "x", "url": "ftp://a"}]
    assert_rejected(d, "http:// 或 https://")


def test_link_verified_is_optional_date():
    d = guide_dict(); d["steps"][0]["links"] = [{"title": "x", "url": "https://a.example", "verified": "2026-09-23"}]
    assert Guide.model_validate(d).steps[0].links[0].verified.isoformat() == "2026-09-23"
    d["steps"][0]["links"][0]["verified"] = "上周"
    with pytest.raises(ValidationError):
        Guide.model_validate(d)


def test_link_form_must_exist_when_forms_known():
    d = guide_dict(); d["steps"][0]["links"] = [{"title": "x", "kind": "form_guide", "form": "nope"}]
    errors = validate_guide(Guide.model_validate(d), VOCAB, file_stem="demo-guide", form_ids={"other"})
    assert any("填表指南 nope 不存在" in e for e in errors)


def test_export_pattern_rules():
    d = guide_dict(); d["export_pattern"] = "{foo}"
    assert_rejected(d, "export_pattern")
    d = guide_dict(); d["export_pattern"] = "fixed"
    assert_rejected(d, "至少要包含")


def test_export_name_no_slash():
    d = guide_dict(); d["requirements"][0]["export_name"] = "a/b"
    assert_rejected(d, "export_name")


def test_repository_forms_are_valid():
    from core.forms import load_all_forms
    results = load_all_forms(COMMUNITY_DIR / "forms")
    assert results
    for r in results:
        assert r.valid, f"{r.path.name}: {r.errors}"
