"""攻略类型（spec 004"攻略类型"）：新建攻略时先选类型，不同类型的数据结构、整理规则、校验和预览可以完全不同。

目前只有"办事流程攻略"（community/guides/，spec 002 的 Guide 结构）。旅游攻略等以后加：
在这里登记一个新类型，给它写数据结构、校验、整理用的 skill 和预览页面即可，新建流程（读帖子 → 草稿 → 预览 → 保存）不用改。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GuideType:
    id: str
    name: str
    description: str
    available: bool
    community_subdir: str | None = None  # 发布到 community/ 下的哪个目录
    skill: str | None = None  # Agent 整理时遵循的 skill（.claude/skills/<名字>）

    def to_dict(self) -> dict:
        return asdict(self)


GUIDE_TYPES: list[GuideType] = [
    GuideType(
        id="process",
        name="办事流程攻略",
        description="签证、补贴、证件办理这类事：要准备哪些材料、按什么步骤去办、要多久。",
        available=True,
        community_subdir="guides",
        skill="guide-author",
    ),
    GuideType(
        id="travel",
        name="旅游攻略",
        description="行程、景点、交通、预算。规划中，暂时不能新建（见 docs/BACKLOG.md）。",
        available=False,
    ),
]


def get_guide_type(type_id: str) -> GuideType | None:
    return next((t for t in GUIDE_TYPES if t.id == type_id), None)
