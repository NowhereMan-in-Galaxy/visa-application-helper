"""试用模式（`uv run youtiao --demo`）：在临时文件夹里准备一套虚构资料，不碰真实的材料根目录。

资料全部是虚构的：基本信息写在下面；材料记录复制自 docs/examples/material-index/（同样是虚构示例）。
也用来给 README 拍截图。
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from config import COMMUNITY_DIR, REPO_ROOT
from core.guides import load_guide
from core.material_types import load_vocabulary
from core.models import PersonalProfile
from core.profile_storage import save_personal_profile
from core.tracks import create_track

EXAMPLES = REPO_ROOT / "docs" / "examples" / "material-index"
DEMO_GUIDE = "schengen-tourist"

DEMO_PROFILE = {
    "identity": {
        "surname": "ZHANG", "given_names": "SAN", "native_full_name": "张三", "sex": "male",
        "date_of_birth": "1995-05-20", "birth_city": "SHANGHAI", "birth_country": "中国", "nationality": "中国",
    },
    "passport": {"passport_type": "regular", "issuing_authority": "中国", "issue_date": "2025-01-10",
                 "expiry_date": "2035-01-09"},
    "contact": {
        "home_address": {"street": "1 EXAMPLE ROAD", "city": "SHANGHAI", "province": "SHANGHAI",
                         "postal_code": "200000", "country": "中国"},
        "mailing_same_as_home": True, "primary_phone": "13800000000", "email": "zhang.san@example.com",
    },
    "family": {"marital_status": "single"},
    "employment": {"primary_occupation": "computer_science",
                   "current": {"name": "EXAMPLE TECH CO., LTD.", "job_title": "SOFTWARE ENGINEER"}},
}


def build_demo_root(root: Path, today: date) -> Path:
    """在 root 下准备虚构资料：基本信息、示例材料、一件示例办事。返回 root。"""
    root.mkdir(parents=True, exist_ok=True)
    save_personal_profile(root, PersonalProfile.model_validate(DEMO_PROFILE))
    for sub in ("records", "applications"):
        target = root / "index" / sub
        target.mkdir(parents=True, exist_ok=True)
        for f in sorted((EXAMPLES / sub).glob("*.yaml")):
            shutil.copy(f, target / f.name)
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    guide = load_guide(COMMUNITY_DIR / "guides" / f"{DEMO_GUIDE}.yaml", vocab).guide
    create_track(root, guide, today, title="示例：申根短期旅游签证")
    return root
