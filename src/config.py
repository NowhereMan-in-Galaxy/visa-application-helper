"""读取配置（docs/SPEC-mvp.md 第 3 条：材料根目录路径必须可配置，不能硬编码）。

只有"材料根目录"（真实文件存放的地方）需要可配置——`materials_index/`（结构化索引）
本身就是仓库的一部分，路径永远固定，不需要配置。
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MATERIALS_INDEX_DIR = REPO_ROOT / "materials_index"
# 共享区（specs/002）：大家共同维护的流程攻略和材料类型词表，跟着仓库走，不含个人信息，所以同样不需要配置。
COMMUNITY_DIR = REPO_ROOT / "community"

_CONFIG_FILE = REPO_ROOT / "config.yaml"
_EXAMPLE_CONFIG_FILE = REPO_ROOT / "config.example.yaml"
_DEFAULT_MATERIALS_ROOT = "materials"


def get_materials_root() -> Path:
    """返回材料根目录的绝对路径。

    优先读仓库根目录下的 config.yaml（已被 .gitignore 排除，每个人本地各自维护一份）；
    如果还没创建，退回 config.example.yaml 里的默认值，方便第一次拉下项目就能直接跑起来看效果。
    """
    config_path = _CONFIG_FILE if _CONFIG_FILE.is_file() else _EXAMPLE_CONFIG_FILE
    materials_root_value = _DEFAULT_MATERIALS_ROOT

    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        materials_root_value = data.get("materials_root", _DEFAULT_MATERIALS_ROOT)

    materials_root_path = Path(materials_root_value)
    if not materials_root_path.is_absolute():
        materials_root_path = REPO_ROOT / materials_root_path
    return materials_root_path
