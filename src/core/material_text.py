"""把一份材料文件读成 Agent 能看的内容（specs/007-trip-info 第 2 步）。

只给「让 Agent 整理行程」用：调用方先确认这份材料属于那件办事，这里只管"文件在材料根目录里面、读出文字或图片"。
不写日志、不缓存。
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

MAX_CHARS = 20000
MAX_PDF_PAGES = 10
MAX_SCAN_PAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MIN_TEXT = 20  # PDF 取到的文字少于这么多，按扫描件处理

IMAGE_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


class MaterialReadError(Exception):
    """读不了：文件不在、不在材料根目录里、格式不支持、读不出内容。消息是中文，可以直接给用户看。"""


def resolve(root: Path, file_ref: str | None) -> Path:
    """file_ref 必须落在材料根目录里面（防止改坏的索引记录指向任意系统文件），且文件存在。"""
    if not file_ref:
        raise MaterialReadError("这条材料没有文件")
    base = root.resolve()
    path = (base / file_ref).resolve()
    if base not in path.parents or not path.is_file():
        raise MaterialReadError("找不到这份材料的文件")
    return path


def _cut(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n……（后面还有 {len(text) - MAX_CHARS} 字没读）"
    return text


def _docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError) as e:
        raise MaterialReadError("这份 Word 文件打不开") from e
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'"))


def _pdf(path: Path) -> dict:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
        pages = reader.pages[:MAX_PDF_PAGES]
        text = "\n\n".join((p.extract_text() or "") for p in pages)
    except (PdfReadError, OSError, ValueError) as e:
        raise MaterialReadError("这份 PDF 打不开") from e
    if len(text.strip()) >= MIN_TEXT:
        more = f"\n（共 {len(reader.pages)} 页，只读了前 {MAX_PDF_PAGES} 页）" if len(reader.pages) > MAX_PDF_PAGES else ""
        return {"text": _cut(text) + more}
    # 扫描件：没有文字层，取每页最大的那张嵌入图片
    images = []
    for page in reader.pages[:MAX_SCAN_PAGES]:
        try:
            best = max(page.images, key=lambda im: len(im.data), default=None)
        except Exception:  # noqa: BLE001 — pypdf 对少见的图片编码会抛各种异常，读不出就当没有
            best = None
        if best is not None and len(best.data) <= MAX_IMAGE_BYTES:
            fmt = IMAGE_FORMATS.get(Path(best.name).suffix.lower(), "png")
            images.append((best.data, fmt))
    if not images:
        raise MaterialReadError("这份 PDF 读不出文字（可能是扫描件）")
    return {"images": images}


def read_material(root: Path, file_ref: str | None) -> dict:
    """返回 {"text": ...} 或 {"images": [(bytes, "png" | "jpeg" | "webp"), ...]}；读不了抛 MaterialReadError。"""
    path = resolve(root, file_ref)
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return {"text": _cut(path.read_text(encoding="utf-8", errors="replace"))}
    if suffix == ".docx":
        return {"text": _cut(_docx(path))}
    if suffix == ".pdf":
        return _pdf(path)
    if suffix in IMAGE_FORMATS:
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise MaterialReadError("图片太大（超过 5 MB）")
        return {"images": [(path.read_bytes(), IMAGE_FORMATS[suffix])]}
    raise MaterialReadError(f"不支持读取 {suffix} 文件")
