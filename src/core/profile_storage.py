"""读写 PersonalProfile（spec.md FR-011）。

跟材料索引（材料根目录/index/）里的记录不一样：PersonalProfile 也是真实个人信息、
存在"材料根目录"下（不被 git 追踪），但它只有一份。这里固定用一个约定路径
（materials_root/personal-profile.yaml），不需要像 MaterialRecord 那样走 file_ref 间接引用——
它是申请人级别的单一文档，本来就不需要那套"多条记录、按 id 区分"的机制。

文件还不存在时（比如第一次跑这个项目），返回一份空的 PersonalProfile，而不是报错——
一个新用户本来就应该先看到"还没有个人信息，点这里填写"，不需要预先造一份示例数据。

格式升级（specs/003-personal-profile）：第一版只有 full_name / date_of_birth / nationality /
passport_number / travel_history 几个平铺字段；现在按分组存（identity / passport / ...）。
旧文件照样能读——迁移在 PersonalProfile 的 model_validator 里完成（读的时候在内存里搬家），
下一次保存时才会以新格式写回磁盘。不需要单独跑迁移脚本。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from core.models import PROFILE_GROUPS, PersonalProfile

PROFILE_FILENAME = "personal-profile.yaml"


def _profile_path(materials_root: Path) -> Path:
    return materials_root / PROFILE_FILENAME


class ProfileFileError(ValueError):
    """personal-profile.yaml 存在但读不懂（YAML 语法错、字段名拼错、日期写错……）。

    宁可报错也不"读个大概"：这份文件每次保存都是整份重写，读错了再保存就会把内容弄丢。
    """


def load_personal_profile(materials_root: Path) -> PersonalProfile:
    path = _profile_path(materials_root)
    if not path.is_file():
        return PersonalProfile()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return PersonalProfile.model_validate(data)
    except (yaml.YAMLError, ValidationError) as e:
        raise ProfileFileError(f"{PROFILE_FILENAME} 格式有误，请手动修正后再试：{e}") from e


def save_profile_group(materials_root: Path, group: str, value: BaseModel | dict) -> PersonalProfile:
    """只替换一个分组（例如 education），其余分组和 travel_history 原样保留。

    按分组保存而不是整份覆盖：「出行记录」标签页和「基本信息」标签页各改各的，不会互相
    把对方刚保存的内容冲掉。列表里的条目增删改也走这里——前端把整个分组（含列表）发回来。
    """
    if group not in PROFILE_GROUPS:
        raise KeyError(group)
    _, model = PROFILE_GROUPS[group]
    part = model.model_validate(value.model_dump() if isinstance(value, BaseModel) else value)
    profile = load_personal_profile(materials_root)
    setattr(profile, group, part)
    save_personal_profile(materials_root, profile)
    return profile


def save_personal_profile(materials_root: Path, profile: PersonalProfile) -> None:
    prune_confirmed_none(profile)
    materials_root.mkdir(parents=True, exist_ok=True)
    path = _profile_path(materials_root)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            profile.model_dump(mode="json"),
            f,
            allow_unicode=True,
            sort_keys=False,
        )


def _merge(current, new):
    """对象（dict）逐键合并；列表和普通值整体替换。

    这样 Agent 只补一个字段（例如 family.father.surname）时，不会把父亲的其他字段冲掉；
    列表（学校、工作经历……）没有稳定的 id，只能整体替换，调用方要把整个列表发回来。
    """
    if isinstance(current, dict) and isinstance(new, dict):
        merged = dict(current)
        for k, v in new.items():
            merged[k] = _merge(current.get(k), v)
        return merged
    return new


def update_profile_fields(materials_root: Path, group: str, changes: dict) -> tuple[PersonalProfile, list[dict]]:
    """只改一个分组里的指定字段（给填表 Agent 写回用户的回答，specs/003「MCP 工具」）。

    和 save_profile_group 的区别：save_profile_group 要整组发送（网页用），这里只发要改的字段，
    没提到的字段保持原样。返回 (保存后的资料, 变化列表 [{field, before, after}])；
    值没有变化时不写文件，变化列表为空。
    分组名不对抛 KeyError；字段名不对、值不合法抛 pydantic ValidationError（文件不会被改动）。
    """
    profile, part, changed = _apply_fields(materials_root, group, changes)
    if changed:
        setattr(profile, group, part)
        save_personal_profile(materials_root, profile)
    return profile, changed


def preview_profile_fields(materials_root: Path, group: str, changes: dict) -> list[dict]:
    """和 update_profile_fields 一样校验并算出变化列表，但不写文件（界面 Agent 的"提议"用，spec 004 第 3 步）。"""
    return _apply_fields(materials_root, group, changes)[2]


def _apply_fields(materials_root: Path, group: str, changes: dict):
    if group not in PROFILE_GROUPS:
        raise KeyError(group)
    _, model = PROFILE_GROUPS[group]
    profile = load_personal_profile(materials_root)
    before = getattr(profile, group).model_dump(mode="json")
    part = model.model_validate(_merge(before, changes))
    after = part.model_dump(mode="json")
    changed = [
        {"field": k, "before": before[k], "after": after[k]}
        for k in changes
        if before[k] != after[k]
    ]
    return profile, part, changed


def _is_empty(value) -> bool:
    """None / 空串 / 空列表 / 所有子字段都空的对象，都算"没有值"。"""
    if value in (None, "", []):
        return True
    if isinstance(value, dict):
        return all(_is_empty(v) for v in value.values())
    return False


def _field_value(profile: PersonalProfile, path: str):
    group, _, key = path.partition(".")
    return getattr(profile, group).model_dump(mode="json")[key]


def prune_confirmed_none(profile: PersonalProfile) -> None:
    """已经有值的字段移出 confirmed_none，避免"清单说没有、实际又填了"的矛盾。"""
    profile.confirmed_none = [p for p in profile.confirmed_none if _is_empty(_field_value(profile, p))]


def confirm_profile_none(materials_root: Path, paths: list[str]) -> tuple[PersonalProfile, list[str]]:
    """把用户确认"没有"的字段加进 confirmed_none，返回 (保存后的资料, 新加进去的路径)。

    路径不存在、是是非题（应直接写 false）或该字段已经有值时抛 ValueError，文件不改动。
    """
    profile = load_personal_profile(materials_root)
    try:
        candidate = PersonalProfile.model_validate(
            {**profile.model_dump(mode="json"), "confirmed_none": [*profile.confirmed_none, *paths]}
        )
    except ValidationError as e:
        raise ValueError(str(e)) from e
    filled = [p for p in paths if not _is_empty(_field_value(candidate, p))]
    if filled:
        raise ValueError(f"这些字段已经有值，不能标记为「没有」：{', '.join(filled)}")
    added = [p for p in candidate.confirmed_none if p not in profile.confirmed_none]
    if added:
        save_personal_profile(materials_root, candidate)
    return candidate, added


def unconfirm_profile_none(materials_root: Path, paths: list[str]) -> tuple[PersonalProfile, list[str]]:
    """把字段从 confirmed_none 里撤掉（用户说"其实不是没有"），返回 (保存后的资料, 真正撤掉的路径)。

    不在清单里的路径直接忽略；什么都没撤掉时不写文件。
    """
    profile = load_personal_profile(materials_root)
    removed = [p for p in profile.confirmed_none if p in paths]
    if removed:
        profile.confirmed_none = [p for p in profile.confirmed_none if p not in paths]
        save_personal_profile(materials_root, profile)
    return profile, removed


# 由其他字段推出"不适用"的规则：字段路径 → (判断函数, 原因)。判断依据的字段没填时不推断，照常算 missing。
_NOT_APPLICABLE_RULES = {
    "contact.mailing_address": (lambda p: p.contact.mailing_same_as_home is True, "邮寄地址与家庭住址相同"),
    "family.spouse": (lambda p: p.family.marital_status in ("single", "divorced", "widowed"), "当前没有配偶"),
    "family.former_spouses": (lambda p: p.family.marital_status == "single", "未婚"),
    "employment.occupation_explanation": (
        lambda p: p.employment.primary_occupation is not None
        and p.employment.primary_occupation not in ("not_employed", "other"),
        "只有待业或「其他」职业才需要说明",
    ),
}


def profile_gaps(profile: PersonalProfile) -> dict:
    """填表前查缺口（DS-160）：按 DS-160 页面列出每个有 ds160 提示的顶层字段的状态。

    状态：filled（有值；是非题 true/false 都算已答）、confirmed_none（用户确认没有）、
    not_applicable（按 _NOT_APPLICABLE_RULES 由其他字段推出不用填，附 reason）、
    missing（没填也没确认，要问用户）。只做机械判断；信息之间是否矛盾由 Agent 另外核对。
    返回 {"summary": {状态: 数量}, "pages": [{"page", "fields": [{path, label, sensitive, ds160, status}]}]}，
    页面顺序按字段定义顺序第一次出现的先后。
    """
    from core.models import describe_personal_profile

    pages: dict[str, list[dict]] = {}
    summary = {"filled": 0, "confirmed_none": 0, "not_applicable": 0, "missing": 0}
    for group in describe_personal_profile():
        values = getattr(profile, group["key"]).model_dump(mode="json")
        for f in group["fields"]:
            if not f["ds160"]:
                continue
            path = f"{group['key']}.{f['key']}"
            if not _is_empty(values[f["key"]]):
                status = "filled"
            elif path in profile.confirmed_none:
                status = "confirmed_none"
            elif path in _NOT_APPLICABLE_RULES and _NOT_APPLICABLE_RULES[path][0](profile):
                status = "not_applicable"
            else:
                status = "missing"
            summary[status] += 1
            page = f["ds160"].split(" · ")[0]
            entry = {"path": path, "label": f["label"], "sensitive": f["sensitive"], "ds160": f["ds160"], "status": status}
            if status == "not_applicable":
                entry["reason"] = _NOT_APPLICABLE_RULES[path][1]
            pages.setdefault(page, []).append(entry)
    return {"summary": summary, "pages": [{"page": p, "fields": fs} for p, fs in pages.items()]}
