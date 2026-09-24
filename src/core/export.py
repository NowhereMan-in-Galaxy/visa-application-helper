"""把一件办事已确认的材料导出到一个文件夹（specs/002 "导出"）。

只**复制**，不移动、不改名原文件：材料根目录里的原件永远保持原样。每次导出都在目标位置
（默认材料根目录下的 exports/，也可以是用户选的桌面等文件夹）新建一个带时间戳的文件夹，
不覆盖上一次导出的结果；文件夹里附一份"清单.txt"，写清楚导出了什么、还缺什么。

文件名按攻略里的 export_pattern / export_name 生成（例如按官方清单编号"01-护照复印件.pdf"），
同名时自动追加 -2、-3，保证不会互相覆盖。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.models import MaterialRecord
from core.tracks import TrackView

STATE_TEXT = {
    "missing": "缺",
    "stale": "需重新开具",
    "unconfirmed": "有候选但还没确认",
    "undecided": "取决于还没回答的问题",
}


@dataclass
class ExportResult:
    folder: Path
    copied: list[str] = field(default_factory=list)  # 导出后的文件名
    missing_files: list[str] = field(default_factory=list)  # 已确认，但记录没有对应文件或文件找不到
    pending: list[str] = field(default_factory=list)  # 还没备齐的需求（名称 + 原因）


def _safe_name(text: str) -> str:
    """去掉文件名里不能用或容易出问题的字符（/ \\ : * ? " < > | 和换行）。"""
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", text).strip(" .") or "材料"


def _unique_folder(base: Path) -> Path:
    folder, n = base, 2
    while folder.exists():
        folder, n = base.with_name(f"{base.name}-{n}"), n + 1
    return folder


def _unique_file(folder: Path, stem: str, suffix: str) -> Path:
    target, n = folder / f"{stem}{suffix}", 2
    while target.exists():
        target, n = folder / f"{stem}-{n}{suffix}", n + 1
    return target


def export_file_stem(pattern: str, seq: int, name: str, part: str | None) -> str:
    """按模板生成文件名（不含后缀）。组合材料导出多份文件而模板里没写 {part} 时，自动追加"-部分名"。"""
    stem = pattern.format(seq=seq, name=_safe_name(name), part=_safe_name(part) if part else "")
    if part and "{part" not in pattern:
        stem = f"{stem}-{_safe_name(part)}"
    return _safe_name(stem.strip(" -_"))


def export_track(
    view: TrackView,
    records: list[MaterialRecord],
    materials_root: Path,
    now: datetime,
    dest_root: Path | None = None,
) -> ExportResult:
    """dest_root 为 None 时导出到 <材料根目录>/exports/；调用方负责先校验 dest_root 是否允许写入。"""
    records_by_id = {r.id: r for r in records}
    root = materials_root.resolve()
    base_dir = dest_root if dest_root is not None else materials_root / "exports"
    folder = _unique_folder(base_dir / f"{_safe_name(view.title)}-{now:%Y%m%d-%H%M}")
    folder.mkdir(parents=True)
    result = ExportResult(folder=folder)

    index = 0
    for req in view.requirements:
        if req.state == "not_applicable":
            continue
        if req.state != "ready":
            if not req.optional:
                result.pending.append(f"{req.name}（{STATE_TEXT.get(req.state, req.state)}）")
            continue
        index += 1
        multi = len(req.records) > 1
        for rec_view in req.records:
            record = records_by_id.get(rec_view.id)
            src = (root / record.file_ref).resolve() if record and record.file_ref else None
            # file_ref 必须落在材料根目录里面：防止一条被改坏的索引记录把任意系统文件"导出"出来
            if src is None or root not in src.parents or not src.is_file():
                result.missing_files.append(f"{req.name}：{rec_view.type}")
                continue
            stem = export_file_stem(
                view.export_pattern, index, req.export_name or req.name, rec_view.type if multi else None
            )
            target = _unique_file(folder, stem, src.suffix)
            shutil.copy2(src, target)
            result.copied.append(target.name)

    lines = [f"{view.title}", f"照着攻略：{view.guide_title}", f"导出时间：{now:%Y-%m-%d %H:%M}", ""]
    lines += ["【已导出】"] + ([f"  {n}" for n in result.copied] or ["  （无）"]) + [""]
    if result.missing_files:
        lines += ["【已确认但找不到文件，请手动补】"] + [f"  {n}" for n in result.missing_files] + [""]
    lines += ["【还没备齐】"] + ([f"  {n}" for n in result.pending] or ["  （无，全部备齐）"])
    (folder / "清单.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
