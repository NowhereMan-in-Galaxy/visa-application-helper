"""读取 materials_index/ 下的 YAML 记录（docs/SPEC-mvp.md 第 3 条：仓库里只存结构化索引，不存真实材料）。

目录约定：
    materials_index/
        applications/<visa_application_id>.yaml   一个 VisaApplication
        records/<material_record_id>.yaml           一条 MaterialRecord

（子目录特意不叫 materials——那样会跟"材料根目录"materials/ 撞名，容易搞混，
也会被 .gitignore 里那条 `materials/` 规则意外忽略掉。）

User Story 1 只需要"读"；User Story 4（前端自主新增材料，见 FR-012）加上了"写"——
`save_material_record` 只管把一条已经构造好的 MaterialRecord 写成 YAML 文件，
不重复利用已有 id、不覆盖已有文件（FR-009 的"不能静默覆盖"原则），文件放哪由调用方决定。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.models import MaterialRecord, VisaApplication


class RecordIdConflictError(Exception):
    """已经存在同名的材料记录，调用方应该换一个 id 或者提示用户。"""


def _load_yaml_files(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    documents = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as f:
            documents.append(yaml.safe_load(f))
    return documents


def load_visa_applications(materials_index_dir: Path) -> list[VisaApplication]:
    raw_docs = _load_yaml_files(materials_index_dir / "applications")
    return [VisaApplication.model_validate(doc) for doc in raw_docs]


def load_material_records(materials_index_dir: Path) -> list[MaterialRecord]:
    raw_docs = _load_yaml_files(materials_index_dir / "records")
    return [MaterialRecord.model_validate(doc) for doc in raw_docs]


def load_materials_for_application(
    materials_index_dir: Path, application_id: str
) -> list[MaterialRecord]:
    all_records = load_material_records(materials_index_dir)
    return [r for r in all_records if r.belongs_to == application_id]


def save_material_record(materials_index_dir: Path, record: MaterialRecord) -> Path:
    """把一条材料记录写成 YAML 文件。id 已存在时报错，而不是静默覆盖（呼应 FR-009 的原则）。"""
    records_dir = materials_index_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    path = records_dir / f"{record.id}.yaml"
    if path.exists():
        raise RecordIdConflictError(f"材料记录 id 已存在：{record.id}")
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(record.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)
    return path


def overwrite_material_record(materials_index_dir: Path, record: MaterialRecord) -> Path:
    """更新一条*已经存在*的材料记录——跟 save_material_record 反过来：这里就是要覆盖。

    目前唯一的调用场景是"追加新页之后把 obtained_date 更新成今天"，record.id 不变。
    """
    path = materials_index_dir / "records" / f"{record.id}.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(record.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)
    return path
