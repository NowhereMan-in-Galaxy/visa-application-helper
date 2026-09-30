"""试用模式（`uv run youtiao --demo`）：在临时文件夹里准备一套虚构资料，不碰真实的材料根目录。

资料全部是虚构的：基本信息写在下面；材料记录复制自 docs/examples/material-index/（同样是虚构示例）。
也用来给 README 拍截图。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from config import COMMUNITY_DIR, REPO_ROOT
from core.guides import load_guide
from core.material_types import load_vocabulary
from core.models import PersonalProfile
from core.profile_storage import save_personal_profile
from core.tracks import create_track, save_track, set_fact_value

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


# 示例办事预先回答的问题：让材料清单按"在职、去法国"收窄，页面上能看到材料对上的效果
DEMO_FACTS = {"country": "法国", "identity": "在职", "minor": "否", "married": "否", "sponsored": "否"}

# 示例办事的"这次行程"和一份虚构的酒店订单（spec 007）：页面上能看到开始清单和行程信息
DEMO_TRIP = {"purpose": "Tourism", "purpose_detail": "巴黎、里昂旅游",
             "stay_name": "HOTEL EXAMPLE PARIS", "stay_address": {"city": "PARIS", "country": "法国"}, "payer": "self"}
DEMO_HOTEL = """HOTEL EXAMPLE PARIS — Booking confirmation (fictional)
Guest: ZHANG SAN
Check-in: 2026-11-02   Check-out: 2026-11-09
Address: 1 Rue Exemple, 75001 Paris, France
"""


def build_demo_root(root: Path, today: date) -> Path:
    """在 root 下准备虚构资料：基本信息、示例材料、一件示例办事。返回 root。"""
    root.mkdir(parents=True, exist_ok=True)
    save_personal_profile(root, PersonalProfile.model_validate(DEMO_PROFILE))
    records = root / "index" / "records"
    records.mkdir(parents=True, exist_ok=True)
    for f in sorted((EXAMPLES / "records").glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        # id 以 example- 开头的记录永远不参与匹配（防止示例数据被当成真实材料，见 core/tracks.py）。
        # 试用模式整个目录都是虚构的，所以换成 demo- 开头，让它们能对上示例办事。
        data["id"] = "demo-" + data["id"].removeprefix("example-")
        data.pop("belongs_to", None)
        (records / f"{data['id']}.yaml").write_text(
            "# 试用模式的虚构资料\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    guide = load_guide(COMMUNITY_DIR / "guides" / f"{DEMO_GUIDE}.yaml", vocab).guide
    track = create_track(root, guide, today, title="示例：申根短期旅游签证")
    for fact, value in DEMO_FACTS.items():
        if fact in guide.facts:
            set_fact_value(guide, track, fact, value)
    from core.trip import merge_trip

    track.trip = merge_trip(track.trip, DEMO_TRIP)
    hotel = root / "other" / "demo-hotel-booking.txt"
    hotel.parent.mkdir(parents=True, exist_ok=True)
    hotel.write_text(DEMO_HOTEL, encoding="utf-8")
    (records / "demo-hotel-booking.yaml").write_text("# 试用模式的虚构资料\n" + yaml.safe_dump({
        "id": "demo-hotel-booking", "category": "other", "type": "酒店预订单", "material_type": "hotel_reservation",
        "obtained_date": today.isoformat(), "file_ref": "other/demo-hotel-booking.txt", "for_track": track.id,
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    save_track(root, track)
    return root
