"""填表对照清单（specs/005-fill-engine「对照清单」）：把「基本信息」整理成方便手动复制的一张表。

用在禁止自动化的官网（例如 ImmiAccount）：页面开在本机，用户自己看着复制粘贴，软件不碰官网。
和填表引擎共用同义词表：英文叫法放进 terms，页面上可以用官网上看到的英文搜到对应的一项。
"""

from __future__ import annotations

from datetime import date
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from core.models import PROFILE_GROUPS, PersonalProfile, _strip_optional
from form_engine.match import MONTHS, Dictionary, _country_row

DATE_FORMATS = [("DD/MM/YYYY", "%d/%m/%Y"), ("YYYY-MM-DD", "%Y-%m-%d"), ("MM/DD/YYYY", "%m/%d/%Y")]


def _date_values(d: date) -> list[dict]:
    out = [{"text": d.strftime(fmt), "hint": name} for name, fmt in DATE_FORMATS]
    out.append({"text": f"{d.day:02d} {MONTHS[d.month - 1][:3].upper()} {d.year}", "hint": "DD MMM YYYY"})
    return out


def _values(value: Any, ann: Any, extra: dict, d: Dictionary) -> list[dict]:
    """一个字段可以复制的写法。空值返回 []。"""
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, date):
        return _date_values(value)
    if isinstance(value, bool):
        return [{"text": "Yes" if value else "No", "hint": "是" if value else "否"}]
    options = extra.get("options") or {}
    if options:
        english = (d.values.get(str(value)) or [str(value).replace("_", " ")])[0]
        return [{"text": english[:1].upper() + english[1:], "hint": options.get(str(value), "")}]
    text = str(value)
    row = _country_row(text, d)
    if row and row[0] != text:
        return [{"text": row[0], "hint": "英文"}, {"text": text, "hint": "原文"}]
    return [{"text": text}]


def _terms(path: str, extra: dict, d: Dictionary) -> list[str]:
    """搜索用的英文叫法：同义词表里的词 + DS-160 提示。列表里的条目按去掉序号后的路径查。"""
    generic = ".".join(p for p in path.split(".") if not p.isdigit())
    terms: list[str] = []
    for e in d.entries:
        if e.path == generic:
            terms += [w for group in e.match for w in group]
    if extra.get("ds160"):
        terms.append(str(extra["ds160"]))
    return list(dict.fromkeys(terms))


def _walk(model: type[BaseModel], data: dict, path: str, labels: list[str], d: Dictionary, out: list[dict]) -> None:
    for name, f in model.model_fields.items():
        ann = _strip_optional(f.annotation)
        extra = f.json_schema_extra if isinstance(f.json_schema_extra, dict) else {}
        title = f.title or name
        value = data.get(name)
        here = f"{path}.{name}"
        if get_origin(ann) is list:
            inner = get_args(ann)[0]
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                for idx, item in enumerate(value or []):
                    _walk(inner, item or {}, f"{here}.{idx}", [*labels, f"{title} {idx + 1}"], d, out)
                continue
            vals = [{"text": str(v)} for v in (value or []) if v not in (None, "")]
            if vals:
                out.append({"path": here, "label": " › ".join([*labels, title]), "sensitive": bool(extra.get("sensitive")),
                            "terms": _terms(here, extra, d), "values": vals})
            continue
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            _walk(ann, value or {}, here, [*labels, title], d, out)
            continue
        vals = _values(value, ann, extra, d)
        if vals:
            out.append({"path": here, "label": " › ".join([*labels, title]), "sensitive": bool(extra.get("sensitive")),
                        "terms": _terms(here, extra, d), "values": vals})


def reference(profile: PersonalProfile, d: Dictionary) -> dict:
    """{"groups": [{"key", "label", "items": [{path, label, sensitive, terms, values: [{text, hint?}]}]}]}

    只列有值的字段；分组内的 label 不再重复分组名。
    """
    groups = []
    for key, (label, model) in PROFILE_GROUPS.items():
        items: list[dict] = []
        _walk(model, getattr(profile, key).model_dump(mode="python"), key, [], d, items)
        if items:
            groups.append({"key": key, "label": label, "items": items})
    return {"groups": groups}
