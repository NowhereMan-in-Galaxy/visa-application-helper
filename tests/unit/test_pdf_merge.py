"""护照盖章页"追加新页"功能（核心库部分，不走 API）。"""

import io

import img2pdf
import pytest
from pypdf import PdfReader, PdfWriter

from core.pdf_merge import UnsupportedPageFormatError, append_page


def _make_pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _make_image_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_append_pdf_page_increases_page_count(tmp_path):
    existing = tmp_path / "stamped-pages.pdf"
    existing.write_bytes(_make_pdf_bytes(page_count=2))

    new_page_pdf = _make_pdf_bytes(page_count=1)
    append_page(existing, "new-page.pdf", new_page_pdf)

    reader = PdfReader(str(existing))
    assert len(reader.pages) == 3


def test_append_image_page_converts_and_appends(tmp_path):
    existing = tmp_path / "stamped-pages.pdf"
    existing.write_bytes(_make_pdf_bytes(page_count=1))

    append_page(existing, "scan.png", _make_image_bytes())

    reader = PdfReader(str(existing))
    assert len(reader.pages) == 2


def test_no_backup_file_left_behind_after_success(tmp_path):
    existing = tmp_path / "stamped-pages.pdf"
    existing.write_bytes(_make_pdf_bytes(page_count=1))

    append_page(existing, "new-page.pdf", _make_pdf_bytes(page_count=1))

    assert not existing.with_name(existing.name + ".bak").exists()


def test_unsupported_format_rejected_without_touching_original(tmp_path):
    existing = tmp_path / "stamped-pages.pdf"
    original_bytes = _make_pdf_bytes(page_count=1)
    existing.write_bytes(original_bytes)

    with pytest.raises(UnsupportedPageFormatError):
        append_page(existing, "notes.txt", b"just some text")

    # 原文件应该完全没变，也不该留下备份文件。
    assert existing.read_bytes() == original_bytes
    assert not existing.with_name(existing.name + ".bak").exists()


def test_broken_pdf_restores_original_via_backup(tmp_path):
    existing = tmp_path / "stamped-pages.pdf"
    original_bytes = _make_pdf_bytes(page_count=1)
    existing.write_bytes(original_bytes)

    # 文件名后缀是 .pdf，但内容根本不是合法 PDF——img2pdf 不会拦截它（后缀检查通过），
    # 真正的错误要等 pypdf 尝试解析的时候才会出现，用来验证失败路径会把原文件恢复回去。
    with pytest.raises(Exception):
        append_page(existing, "corrupt.pdf", b"not a real pdf")

    assert existing.read_bytes() == original_bytes
    assert not existing.with_name(existing.name + ".bak").exists()
