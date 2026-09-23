"""specs/002 导出：只复制已确认的材料，不覆盖旧导出，不导出材料根目录以外的文件。"""

from datetime import date, datetime

from core.export import export_track
from core.models import MaterialCategory, MaterialRecord
from core.tracks import Track, compute_track_view

from guide_fixtures import VOCAB, make_guide

TODAY = date(2026, 9, 23)
NOW = datetime(2026, 9, 23, 10, 30, 0)


def setup(tmp_path, file_ref="financial_snapshot/b.pdf", matches=None):
    (tmp_path / "financial_snapshot").mkdir()
    (tmp_path / "financial_snapshot" / "b.pdf").write_bytes(b"%PDF fake")
    rec = MaterialRecord(id="b", category=MaterialCategory.FINANCIAL_SNAPSHOT, type="银行流水",
                         obtained_date=date(2026, 9, 20), file_ref=file_ref)
    guide = make_guide()
    track = Track(id="t1", guide=guide.id, title="我的", created=TODAY,
                  facts={"identity": "学生", "sponsored": "否"}, matches=matches if matches is not None else {"r-bank": ["b"]})
    return compute_track_view(guide, track, [rec], VOCAB, TODAY), [rec]


def test_copies_confirmed_material_and_writes_manifest(tmp_path):
    view, records = setup(tmp_path)
    result = export_track(view, records, tmp_path, NOW)
    assert result.folder == tmp_path / "exports" / "t1-20260923-103000"
    assert result.copied == ["01-银行流水.pdf"]
    assert (result.folder / "01-银行流水.pdf").read_bytes() == b"%PDF fake"
    assert (tmp_path / "financial_snapshot" / "b.pdf").exists()  # 原件还在
    assert "护照全部页（缺）" in result.pending
    assert "清单" in (result.folder / "清单.txt").name


def test_unconfirmed_material_not_exported(tmp_path):
    view, records = setup(tmp_path, matches={})
    result = export_track(view, records, tmp_path, NOW)
    assert result.copied == []
    assert any("银行流水" in p for p in result.pending)


def test_second_export_gets_new_folder(tmp_path):
    view, records = setup(tmp_path)
    first = export_track(view, records, tmp_path, NOW)
    second = export_track(view, records, tmp_path, NOW)
    assert first.folder != second.folder and second.folder.name.endswith("-2")


def test_file_outside_materials_root_is_refused(tmp_path):
    view, records = setup(tmp_path, file_ref="../../etc/passwd")
    result = export_track(view, records, tmp_path, NOW)
    assert result.copied == [] and result.missing_files
