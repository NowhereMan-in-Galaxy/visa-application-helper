"""读取配置（docs/SPEC-mvp.md 第 3 条：材料根目录路径必须可配置，不能硬编码）。

只有"材料根目录"（真实文件存放的地方）需要可配置。材料索引（每份材料的类型、日期、文件路径）
也是个人信息，2026-09-24 起放在材料根目录下的 `index/` 里，跟着材料根目录走，不再放在仓库里。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
# 共享区（specs/002）：大家共同维护的流程攻略和材料类型词表，跟着仓库走，不含个人信息，所以同样不需要配置。
COMMUNITY_DIR = REPO_ROOT / "community"

_CONFIG_FILE = REPO_ROOT / "config.yaml"
_EXAMPLE_CONFIG_FILE = REPO_ROOT / "config.example.yaml"
_DEFAULT_MATERIALS_ROOT = "materials"


# 临时换一个材料根目录（例如 `uv run youtiao --demo` 的虚构资料）：优先于 config.yaml。
# 用环境变量是因为网页调起的 Agent 和它的 MCP 服务是子进程，会继承同一个值，看到的是同一套资料。
MATERIALS_ROOT_ENV = "YOUTIAO_MATERIALS_ROOT"


def get_materials_root() -> Path:
    """返回材料根目录的绝对路径。

    环境变量 YOUTIAO_MATERIALS_ROOT 有值时用它；否则读仓库根目录下的 config.yaml（已被 .gitignore 排除，
    每个人本地各自维护一份）；还没创建时退回 config.example.yaml 里的默认值，方便第一次拉下项目就能直接跑起来看效果。
    """
    override = os.environ.get(MATERIALS_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
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


def get_materials_index_dir() -> Path:
    """返回材料索引目录：材料根目录下的 index/（里面分 records/ 和 applications/）。"""
    return get_materials_root() / "index"
