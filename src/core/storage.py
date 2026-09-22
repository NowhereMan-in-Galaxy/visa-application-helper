"""读取 materials_index/ 下的 YAML 记录（docs/SPEC-mvp.md 第 3 条：仓库里只存结构化索引，不存真实材料）。

目录约定：
    materials_index/
        applications/<visa_application_id>.yaml   一个 VisaApplication
        records/<material_record_id>.yaml           一条 MaterialRecord

（子目录特意不叫 materials——那样会跟"材料根目录"materials/ 撞名，容易搞混，
也会被 .gitignore 里那条 `materials/` 规则意外忽略掉。）

这一版只做"读"，不做"写"——User Story 1 的验收标准是"手工录入一批材料记录，能在 UI 里看到状态"，
记录本身先靠直接编辑 YAML 文件完成；等做到"引导上传"的 UI 交互时，再补写入的接口。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.models import MaterialRecord, VisaApplication


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
