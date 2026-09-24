"""specs/002 数据结构 §3：材料类型词表的规范化匹配和一致性检查。"""

import pytest

from config import COMMUNITY_DIR
from core.material_types import VocabularyError, build_vocabulary, load_vocabulary


def vocab_with(types, normalize=("原件", "复印件", r"[+]")):
    return build_vocabulary({"normalize": list(normalize), "types": types})


BASIC = [
    {"key": "national_id", "name": "身份证", "category": "passport_scan", "aliases": ["居民身份证"]},
    {"key": "bank_statement", "name": "银行流水", "category": "financial_snapshot", "aliases": ["Bank Statement"]},
]


def test_lookup_strips_decorations_on_both_sides():
    vocab = vocab_with(BASIC)
    assert vocab.lookup("身份证原件 + 复印件") == "national_id"


def test_lookup_ignores_case_and_whitespace():
    vocab = vocab_with(BASIC)
    assert vocab.lookup("  bank   statement ") == "bank_statement"


def test_lookup_is_not_fuzzy():
    vocab = vocab_with(BASIC)
    assert vocab.lookup("身份证明") is None
    assert vocab.lookup(None) is None


def test_duplicate_key_rejected():
    with pytest.raises(VocabularyError, match="key 重复"):
        vocab_with(BASIC + [{"key": "national_id", "name": "别的", "aliases": []}])


def test_alias_conflict_after_normalization_rejected():
    types = BASIC + [{"key": "id_copy", "name": "身份证复印件", "aliases": []}]
    with pytest.raises(VocabularyError, match="别名冲突") as e:
        vocab_with(types)
    assert "national_id" in str(e.value) and "id_copy" in str(e.value)


def test_parts_must_exist_and_be_single_level():
    with pytest.raises(VocabularyError, match="不存在"):
        vocab_with([{"key": "full", "name": "全部", "aliases": [], "parts": ["nope"]}])
    with pytest.raises(VocabularyError, match="只允许一层"):
        vocab_with([
            {"key": "a", "name": "甲", "aliases": []},
            {"key": "b", "name": "乙", "aliases": [], "parts": ["a"]},
            {"key": "c", "name": "丙", "aliases": [], "parts": ["b"]},
        ])


def test_invalid_category_rejected():
    with pytest.raises(VocabularyError, match="category"):
        vocab_with([{"key": "x", "name": "某材料", "category": "not_a_category", "aliases": []}])


def test_repository_vocabulary_is_valid():
    """仓库里真实的共享词表必须能加载——防止有人改坏了还提交上来。"""
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    assert vocab.lookup("户口本整本复印件") == "household_register"
    assert vocab.lookup("最近 3-6 个月银行流水") == "bank_statement"


def test_reusable_must_be_boolean():
    with pytest.raises(VocabularyError, match="reusable"):
        vocab_with([{"key": "x", "name": "某材料", "aliases": [], "reusable": "no"}])


def test_repository_marks_one_off_types():
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    assert vocab.types["itinerary"].reusable is False
    assert vocab.types["national_id"].reusable is True
