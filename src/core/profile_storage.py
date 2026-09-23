"""读写 PersonalProfile（spec.md FR-011）。

跟 materials_index/ 里的其它记录不一样：PersonalProfile 的实际内容是真实个人信息，
必须存在"材料根目录"下（不被 git 追踪），不能进仓库。这里固定用一个约定路径
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
    materials_root.mkdir(parents=True, exist_ok=True)
    path = _profile_path(materials_root)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            profile.model_dump(mode="json"),
            f,
            allow_unicode=True,
            sort_keys=False,
        )
