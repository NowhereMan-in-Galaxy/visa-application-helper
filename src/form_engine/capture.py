"""把官网页面上已经填好的内容存回「基本信息」（specs/006-browser-extension 第三版「存进基本信息」）。

和 match.plan 反过来：plan 是"基本信息 → 页面"，这里是"页面 → 基本信息"。
只处理认得出字段路径的格子；这次行程专属的内容（旅行目的、日期……）认不出，自然不会存。
这里只算"建议改什么"，不写文件；用户在侧边栏勾选确认后，由 apply() 写入。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from core.models import PROFILE_GROUPS, PersonalProfile, _strip_optional
from form_engine.match import (
    MONTHS, TRIP, Dictionary, Leaf, date_format, match_field, normalize, profile_leaves, profile_value,
)

MAX_VALUE = 500


# ---------------------------------------------------------------- 页面上的文字 → 基本信息的值

def enum_options(path: str) -> list[str]:
    """选择题字段允许的取值（模型里的 Literal）。"""
    from core.trip import TripInfo

    group, *rest = path.split(".")
    model: Any = TripInfo if group == TRIP else PROFILE_GROUPS[group][1]
    ann: Any = None
    for name in rest:
        if not (isinstance(model, type) and issubclass(model, BaseModel)) or name not in model.model_fields:
            return []
        ann = _strip_optional(model.model_fields[name].annotation)
        model = ann
    return [str(x) for x in get_args(ann)] if get_origin(ann) is Literal else []


def _country(text: str, d: Dictionary) -> list[str] | None:
    """"CHINA - CHN"、"China (PRC)" 这类写法：整段或去掉后面的代码后，能对上国家表的哪一行。"""
    for t in (text, re.split(r"\s+-\s+|\s*\(", text)[0]):
        v = normalize(t)
        for row in d.countries:
            if v in {normalize(x) for x in row}:
                return row
    return None


def _same_words(a: str, b: str) -> bool:
    return set(normalize(a).split()) == set(normalize(b).split())


def enum_value(text: str, path: str, d: Dictionary) -> str | None:
    """"Never Married" → single。按 fill.js 的顺序找：完全相同 → 以它开头 → 词相同 → 包含全部词；只接受唯一一个。"""
    t = normalize(text)
    if not t:
        return None
    options = enum_options(path)
    syn = {k: [normalize(s) for s in d.values.get(k, [k, k.replace("_", " ")])] for k in options}
    tests = [
        lambda s: t == s,
        lambda s: t.startswith(s + " "),
        lambda s: set(t.split()) == set(s.split()),
        lambda s: set(s.split()) <= set(t.split()),
    ]
    for ok in tests:
        hits = {k for k, words in syn.items() if any(s and ok(s) for s in words)}
        if len(hits) == 1:
            return hits.pop()
        if len(hits) > 1:
            return None
    return None


_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NAMED = re.compile(r"^(\d{1,2})[\s\-/.]+([a-z]{3,9})[\s\-/.,]+(\d{4})$|^([a-z]{3,9})[\s\-/.]+(\d{1,2})[\s\-/.,]+(\d{4})$")


def parse_date(text: str, fmt: str | None) -> date | None:
    """页面上的日期文字 → 日期。认得：2002-03-09、09 MAR 2002、Mar 9, 2002；dd/mm/yyyy 这种只有知道格式时才认。"""
    s = (text or "").strip().lower()
    try:
        if m := _ISO.match(s):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _NAMED.match(s):
            day, mon, year = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
            month = next((k + 1 for k, name in enumerate(MONTHS) if name.startswith(mon[:3])), None)
            return date(int(year), month, int(day)) if month else None
        if fmt and "mmm" not in fmt:
            nums = re.findall(r"\d+", s)
            order = re.findall(r"dd|mm|yyyy", fmt)
            if len(nums) == 3 and len(order) == 3:
                parts = dict(zip(order, map(int, nums)))
                return date(parts["yyyy"], parts["mm"], parts["dd"])
    except ValueError:
        return None
    return None


def _yes_no(text: str, d: Dictionary) -> bool | None:
    t = normalize(text)
    if t in {normalize(x) for x in d.values["yes"]}:
        return True
    if t in {normalize(x) for x in d.values["no"]}:
        return False
    return None


# ---------------------------------------------------------------- 建议

def _show(value: Any) -> str | None:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def suggest(fields: list[dict], values: dict, profile: PersonalProfile, d: Dictionary,
            site_date_format: str | None = None, trip: Any = None) -> list[dict]:
    """页面上的值和基本信息不一样的格子 → 建议列表。

    每项：{i, path, label, sensitive, before, after, value, action}；action 为 "set"（写值）
    或 "none"（记为"没有"，来自"有没有……"题选了 No）。同一个字段在页面上出现多次时只留第一个。
    trip.* 的格子（spec 007）只有给了 trip（选了"这件事"）时才建议，保存时写进这件办事。
    """
    leaves = profile_leaves()
    out: list[dict] = []
    seen: set[str] = set()
    for f in fields:
        i = f.get("i")
        raw = values.get(str(i), values.get(i)) if isinstance(values, dict) else None
        if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_VALUE:
            continue
        raw = raw.strip()
        path = match_field(f, d)
        if path is None or path in seen or (trip is None and path.startswith(TRIP + ".")):
            continue
        leaf: Leaf = leaves[path]
        current = profile_value(profile, path, trip)
        item = {"i": i, "path": path, "label": leaf.label, "sensitive": leaf.sensitive, "before": _show(current)}

        if leaf.kind == "list":
            # "有没有……"：只把"没有"存下来；"有"的话具体内容页面上另有格子，这里不猜
            # 行程里的列表（同行人）没有"确认过没有"的记法，选了 No 就是空的，不用存
            if path.startswith(TRIP + "."):
                continue
            if _yes_no(raw, d) is False and not current and path not in profile.confirmed_none:
                out.append({**item, "after": "没有", "value": None, "action": "none"})
                seen.add(path)
            continue
        if leaf.kind == "date":
            value: Any = parse_date(raw, date_format(f) or site_date_format)
        elif leaf.kind == "enum":
            value = enum_value(raw, path, d)
        elif leaf.kind == "bool":
            value = _yes_no(raw, d)
        else:
            row = _country(raw, d)
            if row and current and _country(str(current), d) == row:
                continue  # 同一个国家的不同写法（CHINA / CHINA - CHN），不算改动
            value = re.split(r"\s+-\s+[A-Z]{3}$", raw)[0] if row else raw
        if value is None or value == current:
            continue
        if isinstance(value, str) and isinstance(current, str) and _same_words(value, current):
            continue  # 只是大小写、标点不同
        out.append({**item, "after": _show(value), "value": value.isoformat() if isinstance(value, date) else value,
                    "action": "set"})
        seen.add(path)
    return out


# ---------------------------------------------------------------- 写入

def to_changes(items: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """[{path, value, action}] → ({分组: 嵌套的改动}, [记为"没有"的路径])。路径不存在抛 KeyError。

    行程信息在 "trip" 这一组里（调用方写进这件办事，不写基本信息）。
    """
    leaves = profile_leaves()
    groups: dict[str, dict] = {}
    none: list[str] = []
    for it in items:
        path = it["path"]
        if path not in leaves:
            raise KeyError(path)
        if it.get("action") == "none":
            none.append(path)
            continue
        group, *rest = path.split(".")
        cur = groups.setdefault(group, {})
        for name in rest[:-1]:
            cur = cur.setdefault(name, {})
        cur[rest[-1]] = it.get("value")
    return groups, none
