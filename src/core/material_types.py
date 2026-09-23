"""材料类型词表（specs/002-guide-to-track/spec.md "数据结构 §3"）。

核心库，不调用模型：一个叫法能不能对上某个标准类型，完全由词表 + 固定的规范化规则决定，
相同输入永远得到相同结果。认不出的叫法就老老实实返回 None，交给人（或将来的本地 Agent）
去补词表，而不是在这里做"差不多就算"的模糊匹配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.models import MaterialCategory


class VocabularyError(Exception):
    """词表本身有问题（key 重复、别名冲突、parts 引用不存在的 key 等）。"""


@dataclass(frozen=True)
class MaterialType:
    key: str
    name: str
    category: MaterialCategory | None
    aliases: tuple[str, ...]
    parts: tuple[str, ...] = ()
    # 是否是跨事项反复使用的长期材料（证件、流水……）。False = 一次性材料（行程单、解释信……），
    # 在办事里上传时默认只属于那件办事，不进长期资料库。见 specs/002 "长期资料 vs 本次专用"。
    reusable: bool = True


@dataclass
class Vocabulary:
    types: dict[str, MaterialType]
    normalize_patterns: list[re.Pattern] = field(default_factory=list)
    # 规范化后的别名 -> key，构造时算好，查找时只做一次字典查询
    _alias_index: dict[str, str] = field(default_factory=dict)

    def normalize(self, text: str) -> str:
        for pattern in self.normalize_patterns:
            text = pattern.sub("", text)
        return re.sub(r"\s+", "", text).lower()

    def lookup(self, name: str | None) -> str | None:
        """把一个叫法对到标准 key；对不上返回 None。"""
        if not name:
            return None
        return self._alias_index.get(self.normalize(name))

    def name_of(self, key: str | None) -> str | None:
        if key is None or key not in self.types:
            return None
        return self.types[key].name


def build_vocabulary(raw: dict) -> Vocabulary:
    """从已经解析好的 YAML 内容构造词表，并做全部一致性检查。出错时抛 VocabularyError。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), list):
        raise VocabularyError("词表顶层必须是包含 types 列表的对象")

    patterns = []
    for p in raw.get("normalize") or []:
        try:
            patterns.append(re.compile(p))
        except re.error as e:
            raise VocabularyError(f"normalize 规则不是合法的正则：{p!r}（{e}）") from e

    types: dict[str, MaterialType] = {}
    for entry in raw["types"]:
        key = entry.get("key")
        if not key:
            raise VocabularyError(f"有一条词表记录缺少 key：{entry}")
        if key in types:
            raise VocabularyError(f"key 重复：{key}")
        category = entry.get("category")
        try:
            category_value = MaterialCategory(category) if category else None
        except ValueError as e:
            raise VocabularyError(f"{key}：category 取值不合法：{category}") from e
        reusable = entry.get("reusable", True)
        if not isinstance(reusable, bool):
            raise VocabularyError(f"{key}：reusable 只能是 true 或 false")
        types[key] = MaterialType(
            key=key,
            name=entry.get("name") or key,
            category=category_value,
            aliases=tuple(entry.get("aliases") or []),
            parts=tuple(entry.get("parts") or []),
            reusable=reusable,
        )

    for t in types.values():
        for part in t.parts:
            if part not in types:
                raise VocabularyError(f"{t.key}：parts 引用了不存在的 key：{part}")
            if types[part].parts:
                raise VocabularyError(f"{t.key}：parts 只允许一层，{part} 自己也是组合类型")

    vocab = Vocabulary(types=types, normalize_patterns=patterns)
    for t in types.values():
        # 标准名本身也算一个别名，省得每条都要把 name 再抄一遍进 aliases
        for alias in (t.name, *t.aliases):
            normalized = vocab.normalize(alias)
            if not normalized:
                raise VocabularyError(f"{t.key}：别名 {alias!r} 规范化后变成空字符串，请检查 normalize 规则")
            owner = vocab._alias_index.get(normalized)
            if owner is not None and owner != t.key:
                raise VocabularyError(
                    f"别名冲突：{t.key} 的 {alias!r} 规范化后是 {normalized!r}，与 {owner} 的别名相同"
                )
            vocab._alias_index[normalized] = t.key
    return vocab


def load_vocabulary(path: Path) -> Vocabulary:
    with path.open("r", encoding="utf-8") as f:
        return build_vocabulary(yaml.safe_load(f))
