"""读写 PersonalProfile（spec.md FR-011）。

跟 materials_index/ 里的其它记录不一样：PersonalProfile 的实际内容是真实个人信息，
必须存在"材料根目录"下（不被 git 追踪），不能进仓库。这里固定用一个约定路径
（materials_root/personal-profile.yaml），不需要像 MaterialRecord 那样走 file_ref 间接引用——
它是申请人级别的单一文档，本来就不需要那套"多条记录、按 id 区分"的机制。

文件还不存在时（比如第一次跑这个项目），返回一份空的 PersonalProfile，而不是报错——
一个新用户本来就应该先看到"还没有个人信息，点这里填写"，不需要预先造一份示例数据。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.models import PersonalProfile

PROFILE_FILENAME = "personal-profile.yaml"


def _profile_path(materials_root: Path) -> Path:
    return materials_root / PROFILE_FILENAME


def load_personal_profile(materials_root: Path) -> PersonalProfile:
    path = _profile_path(materials_root)
    if not path.is_file():
        return PersonalProfile()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return PersonalProfile.model_validate(data)


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
