"""格子 → 基本信息字段的识别，以及生成填写脚本（specs/005-fill-engine「识别规则」）。

纯函数、确定性：同样的扫描结果 + 同样的基本信息，永远得到同样的计划。
报告部分（除 `script` 外）不含任何基本信息的值；值只写进交给页面运行的脚本里。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_origin

import yaml
from pydantic import BaseModel

from core.models import PROFILE_GROUPS, PersonalProfile, _strip_optional

HERE = Path(__file__).resolve().parent
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
_CJK = re.compile(r"[一-鿿]")


# ---------------------------------------------------------------- 文本规范化

def normalize(text: str | None) -> str:
    """拆驼峰和字母数字交界、转小写、非字母数字（中文保留）换成空格。tbxAPP_SURNAME → tbx app surname。"""
    s = text or ""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    s = re.sub(r"[^0-9a-z一-鿿]+", " ", s.lower())
    return s.strip()


def _hit(phrase: str, text: str) -> bool:
    """中文按包含匹配；英文按整词（整段词组）匹配。两边都已规范化。"""
    if _CJK.search(phrase):
        return phrase in text
    return f" {phrase} " in f" {text} "


# ---------------------------------------------------------------- 基本信息的单值字段

@dataclass(frozen=True)
class Leaf:
    path: str
    label: str
    kind: Literal["str", "date", "bool", "enum"]
    sensitive: bool


def _walk(model: type[BaseModel], prefix: str, labels: list[str], out: dict[str, Leaf]) -> None:
    for name, f in model.model_fields.items():
        ann = _strip_optional(f.annotation)
        extra = f.json_schema_extra if isinstance(f.json_schema_extra, dict) else {}
        path, lab = f"{prefix}.{name}", [*labels, f.title or name]
        if get_origin(ann) is list:
            continue  # 列表字段这一步不填，交给 Agent
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            _walk(ann, path, lab, out)
            continue
        kind = "date" if ann is date else "bool" if ann is bool else "enum" if get_origin(ann) is Literal else "str"
        out[path] = Leaf(path, " › ".join(lab), kind, bool(extra.get("sensitive")))


@lru_cache(maxsize=1)
def profile_leaves() -> dict[str, Leaf]:
    out: dict[str, Leaf] = {}
    for group, (label, model) in PROFILE_GROUPS.items():
        _walk(model, group, [label], out)
    return out


def profile_value(profile: PersonalProfile, path: str) -> Any:
    cur: Any = profile.model_dump(mode="python")
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


# ---------------------------------------------------------------- 同义词表

@dataclass
class Entry:
    path: str
    match: list[list[str]]
    exclude: list[str] = field(default_factory=list)
    autocomplete: list[str] = field(default_factory=list)


@dataclass
class Dictionary:
    entries: list[Entry]
    values: dict[str, list[str]]
    countries: list[list[str]]


class FormFieldsError(ValueError):
    pass


def _flat(items: Any) -> list[str]:
    """YAML 锚点（*others）会展开成嵌套列表，这里拍平成一层字符串。"""
    out: list[str] = []
    for x in items or []:
        out.extend(_flat(x) if isinstance(x, list) else [str(x)])
    return out


def load_dictionary(path: Path) -> Dictionary:
    """读同义词表并检查；有问题抛 FormFieldsError，信息里列出全部错误。"""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise FormFieldsError(str(e)) from e
    leaves = profile_leaves()
    errors: list[str] = []
    entries: list[Entry] = []
    for p, spec in (data.get("fields") or {}).items():
        if p not in leaves:
            errors.append(f"{p}：基本信息里没有这个单值字段")
            continue
        spec = spec or {}
        groups = [[normalize(w) for w in _flat(g)] for g in (spec.get("match") or [])]
        if not groups or any(not g or not all(g) for g in groups):
            errors.append(f"{p}：match 不能为空，每组至少一个词")
            continue
        entries.append(Entry(
            p, groups,
            [w for w in (normalize(x) for x in _flat(spec.get("exclude"))) if w],
            [str(a).lower() for a in _flat(spec.get("autocomplete"))],
        ))
    values = {str(k).lower() if not isinstance(k, bool) else ("yes" if k else "no"): _flat(v)
              for k, v in (data.get("values") or {}).items()}
    countries = [_flat(row) for row in (data.get("countries") or [])]
    if any(not row for row in countries):
        errors.append("countries：每一行至少一个写法")
    if errors:
        raise FormFieldsError("；".join(errors))
    return Dictionary(entries, values, countries)


# ---------------------------------------------------------------- 识别一个格子

def field_text(f: dict) -> str:
    parts = [f.get("label"), f.get("section"), f.get("name"), f.get("placeholder"), f.get("autocomplete")]
    return normalize(" ".join(p for p in parts if p))


def own_text(f: dict) -> str:
    """格子自己的文字（不含小节标题）：命中这里的词比只在小节标题里命中的分量重。"""
    return normalize(" ".join(p for p in (f.get("label"), f.get("name"), f.get("placeholder")) if p))


# 每种格子能填哪类字段（试验 #10：CEAC 的单选题读不到题目文字，只靠小节标题 "Phone" 就被认成了"主要电话"）
_COMPATIBLE = {
    "radio": {"bool", "enum"},
    "select": {"enum", "str", "date"},
    "text": {"str", "date", "enum"},
    "textarea": {"str"},
    "date": {"date"},
}


def match_field(f: dict, d: Dictionary) -> str | None:
    """返回最匹配的字段路径；认不出或并列第一时返回 None。

    排名先看"每组词都命中在格子自己的标签 / 名字里"（own），再看得分：
    试验 #10 里 "Country/Authority that Issued" 被上方小节标题 "Passport Book Number" 带偏，认成了护照本号。
    格子类型和字段类型对不上的（单选题 ↔ 文字字段）直接不考虑。
    """
    text, own = field_text(f), own_text(f)
    auto = set((f.get("autocomplete") or "").lower().split())
    allowed = _COMPATIBLE.get(f.get("kind") or "text", _COMPATIBLE["text"])
    leaves = profile_leaves()
    ranks: dict[str, tuple[bool, int]] = {}
    for e in d.entries:
        if leaves[e.path].kind not in allowed:
            continue
        if auto & set(e.autocomplete):
            ranks[e.path] = (True, 100)
            continue
        if any(_hit(w, text) for w in e.exclude):
            continue
        total, all_own = 0, True
        for group in e.match:
            hits = [len(w) * (2 if _hit(w, own) else 1) for w in group if _hit(w, text)]
            if not hits:
                break
            total += max(hits)
            all_own = all_own and any(_hit(w, own) for w in group)
        else:
            ranks[e.path] = (all_own, total)
    if not ranks:
        return None
    best = max(ranks.values())
    top = [p for p, r in ranks.items() if r == best]
    return top[0] if len(top) == 1 else None


_PART_WORDS = {
    "day": ["day", "dd"], "month": ["month", "mm", "mon"], "year": ["year", "yyyy", "yy"],
}
_PART_CJK = {"day": "日", "month": "月", "year": "年"}


def date_part(f: dict) -> str | None:
    """日期拆成几格时，这一格是日 / 月 / 年中的哪一部分；看不出或像完整日期时返回 None。"""
    auto = (f.get("autocomplete") or "").lower()
    for part in ("day", "month", "year"):
        if f"bday-{part}" in auto:
            return part
    text = field_text({**f, "autocomplete": None})
    cjk = text.replace("日期", "").replace("生日", "")
    found = [p for p, words in _PART_WORDS.items()
             if any(_hit(w, text) for w in words) or _PART_CJK[p] in cjk]
    return found[0] if len(found) == 1 else None


_FMT = re.compile(r"(dd|mmm|mm|yyyy)([/.\- ])(dd|mmm|mm|yyyy)\2(dd|mmm|mm|yyyy)")


def date_format(f: dict) -> str | None:
    raw = f"{f.get('placeholder') or ''} {f.get('label') or ''}".lower()
    m = _FMT.search(raw)
    if not m or {m.group(1), m.group(3), m.group(4)} not in ({"dd", "mm", "yyyy"}, {"dd", "mmm", "yyyy"}):
        return None
    return m.group(0)


def format_date(d: date, fmt: str) -> str:
    return (fmt.replace("yyyy", f"{d.year:04d}").replace("mmm", MONTHS[d.month - 1][:3].upper())
            .replace("mm", f"{d.month:02d}").replace("dd", f"{d.day:02d}"))


# ---------------------------------------------------------------- 值 → 候选写法

def _country_row(value: str, d: Dictionary) -> list[str] | None:
    v = normalize(value)
    for row in d.countries:
        if v in {normalize(x) for x in row}:
            return row
    return None


def candidates(value: Any, leaf: Leaf, d: Dictionary, part: str | None = None) -> list[str]:
    """下拉框 / 单选组里可能的选项写法（fill.js 在页面上做规范化后完全相同的匹配）。"""
    if isinstance(value, date):
        if part == "day":
            return [f"{value.day:02d}", str(value.day)]
        if part == "month":
            name = MONTHS[value.month - 1]
            return [f"{value.month:02d}", str(value.month), name[:3], name, f"{value.month}月"]
        if part == "year":
            return [str(value.year)]
        return []
    if isinstance(value, bool):
        return d.values["yes" if value else "no"]
    s = str(value)
    if leaf.kind == "enum":
        return d.values.get(s, [s, s.replace("_", " ")])
    return _country_row(s, d) or [s]


def text_value(value: Any, leaf: Leaf, d: Dictionary, f: dict, part: str | None) -> str | None:
    """文本框里要写的字；日期看不出格式、是非题写进文本框时返回 None（交给 Agent）。"""
    if isinstance(value, date):
        if part == "day":
            return f"{value.day:02d}"
        if part == "month":
            return f"{value.month:02d}"
        if part == "year":
            return str(value.year)
        if f.get("kind") == "date":
            return value.isoformat()
        fmt = date_format(f)
        return format_date(value, fmt) if fmt else None
    if isinstance(value, bool):
        return None
    if leaf.kind == "enum":
        return candidates(value, leaf, d)[0]
    row = _country_row(str(value), d)
    return row[0] if row else str(value)


# ---------------------------------------------------------------- 扫描结果

_KINDS = {"t": "text", "d": "date", "a": "textarea", "s": "select", "r": "radio"}


class ScanError(ValueError):
    pass


def expand_scan(scan: str | dict | list) -> list[dict]:
    """把 scan.js 的压缩结果（分段读回后拼起来的字符串）展开成格子列表。

    也接受已经展开的列表（以后的插件可以直接传）。拼接出错（少读或重复读了一段）时抛 ScanError。
    """
    if isinstance(scan, list):
        return scan
    if isinstance(scan, str):
        try:
            scan = json.loads(scan)
        except json.JSONDecodeError as e:
            raise ScanError(f"扫描结果不是完整的 JSON，可能少读或重复读了一段：{e}") from e
    if not isinstance(scan, dict) or scan.get("v") != 1:
        raise ScanError("扫描结果格式不对：要用 get_form_scan_script 的脚本扫描")
    sections = scan.get("sections") or []
    out = []
    for row in scan.get("f") or []:
        i, k, label, sec, name, placeholder, auto, filled = row[:8]
        out.append({
            "i": i, "kind": _KINDS.get(k, k), "label": label,
            "section": sections[sec] if isinstance(sec, int) and 0 <= sec < len(sections) else "",
            "name": name, "placeholder": placeholder, "autocomplete": auto, "filled": bool(filled),
            # 第 9 项（可选）：改了会让页面刷新的下拉框（ASP.NET 的 __doPostBack）
            "postback": bool(row[8]) if len(row) > 8 else False,
        })
    return out


# ---------------------------------------------------------------- 生成计划

def _brief(f: dict) -> str:
    return (f.get("label") or f.get("name") or f.get("placeholder") or "")[:60]


def plan(fields: list[dict], profile: PersonalProfile, d: Dictionary,
         allow_sensitive: list[str] | None = None) -> dict:
    leaves = profile_leaves()
    allowed = set(allow_sensitive or [])
    report: dict[str, list] = {k: [] for k in (
        "fill", "sensitive", "missing", "needs_format", "manual", "already_filled", "unmatched")}
    ops: list[dict] = []
    for f in fields:
        i, kind = f.get("i"), f.get("kind")
        if not isinstance(i, int) or kind not in ("text", "date", "textarea", "select", "radio"):
            continue
        if f.get("filled"):
            report["already_filled"].append(i)
            continue
        path = match_field(f, d)
        if path is None:
            report["unmatched"].append({"i": i, "text": _brief(f)})
            continue
        leaf = leaves[path]
        item = {"i": i, "path": path, "label": leaf.label}
        value = profile_value(profile, path)
        if value is None or value == "":
            report["missing"].append(item)
            continue
        if leaf.sensitive and path not in allowed:
            report["sensitive"].append(item)
            continue
        part = date_part(f) if leaf.kind == "date" else None
        if kind == "select" and f.get("postback"):
            # 试验 #6：用脚本改这种下拉框，下一次保存容易 Application Error。交给用户（或 Agent 用真实点击）选
            report["manual"].append(item)
            continue
        if kind in ("select", "radio"):
            cands = candidates(value, leaf, d, part)
            if not cands:
                report["needs_format"].append(item)
                continue
            ops.append({"i": i, "k": kind, "c": cands})
        else:
            v = text_value(value, leaf, d, f, part)
            if v is None:
                report["needs_format"].append(item)
                continue
            ops.append({"i": i, "k": "text", "v": v})
        report["fill"].append(item)
    return {**report, "ops": ops, "script": fill_script(ops)}


# ---------------------------------------------------------------- 页面脚本

def scan_script() -> str:
    return (HERE / "scan.js").read_text(encoding="utf-8")


def fill_script(ops: list[dict]) -> str:
    template = (HERE / "fill.js").read_text(encoding="utf-8")
    return template.replace("__PLAN__", json.dumps(ops, ensure_ascii=False))


def default_dictionary() -> Dictionary:
    from config import COMMUNITY_DIR
    return load_dictionary(COMMUNITY_DIR / "form_fields.yaml")
