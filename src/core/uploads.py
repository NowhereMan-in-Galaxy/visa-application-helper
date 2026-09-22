"""把用户上传的材料文件保存到"材料根目录"（FR-012）。

跟 storage.py 不是一回事：storage.py 读写的是 materials_index/（仓库追踪的元数据），
这里写的是材料根目录（不进仓库，见 docs/SPEC-mvp.md 第 3 条），保存的是文件本身。
"""

from __future__ import annotations

from pathlib import Path


class UploadConflictError(Exception):
    """目标路径已经有文件了，不能静默覆盖（FR-009）。"""


def save_uploaded_file(
    materials_root: Path,
    category: str,
    record_id: str,
    original_filename: str,
    content: bytes,
) -> str:
    """保存文件到 materials_root/<category>/<record_id><原始后缀>，返回相对于
    materials_root 的相对路径，直接拿去当 MaterialRecord.file_ref 用。

    用 record_id 做文件名前缀：record_id 本身已经在 storage.save_material_record
    里保证过全局唯一，这里不用再单独想一套命名规则。
    """
    suffix = Path(original_filename).suffix
    safe_filename = f"{record_id}{suffix}"
    target_dir = materials_root / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_filename

    if target_path.exists():
        raise UploadConflictError(f"文件已存在，不能覆盖：{target_path}")

    target_path.write_bytes(content)
    return f"{category}/{safe_filename}"
