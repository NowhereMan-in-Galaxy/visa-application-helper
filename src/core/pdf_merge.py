"""把新扫描的一页（图片或 PDF）追加进一份已有的 PDF 文件末尾。

典型场景：护照盖章页那份 PDF 已经有好几页旧的出入境章，出国一趟回来又盖了新的章，
把新扫描的这一页拍照/扫描上传，追加到同一份 PDF 里，不用再新建一条材料记录。
"""

from __future__ import annotations

import io
from pathlib import Path

import img2pdf
from pypdf import PdfWriter

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class UnsupportedPageFormatError(Exception):
    """上传的文件既不是 PDF，也不是支持追加的图片格式。"""


def _to_pdf_bytes(filename: str, content: bytes) -> bytes:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return content
    if suffix in _IMAGE_SUFFIXES:
        return img2pdf.convert(content)
    raise UnsupportedPageFormatError(
        f"不支持的文件格式：{suffix or '（无后缀）'}——只接受 PDF 或 jpg/png 图片"
    )


def append_page(existing_pdf_path: Path, new_page_filename: str, new_page_content: bytes) -> None:
    """把新的一页追加到 existing_pdf_path 指向的 PDF 末尾，原地更新这个文件。

    合并前会先把原文件备份成同目录下的 `<文件名>.bak`：如果上传的文件其实是损坏的、
    或者合并过程中出别的错，会用备份把原文件恢复回去，不会留下一份合并到一半的坏文件；
    合并成功后备份会被删掉，不留冗余文件。
    """
    new_page_pdf_bytes = _to_pdf_bytes(new_page_filename, new_page_content)

    backup_path = existing_pdf_path.with_name(existing_pdf_path.name + ".bak")
    backup_path.write_bytes(existing_pdf_path.read_bytes())

    try:
        writer = PdfWriter()
        writer.append(str(existing_pdf_path))
        writer.append(io.BytesIO(new_page_pdf_bytes))
        with existing_pdf_path.open("wb") as f:
            writer.write(f)
    except Exception:
        existing_pdf_path.write_bytes(backup_path.read_bytes())
        raise
    finally:
        backup_path.unlink(missing_ok=True)
