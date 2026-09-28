"""User Story 4（FR-012/FR-013）新增的写入路径：材料记录、上传文件、PersonalProfile。

用 pytest 的 tmp_path 隔离文件系统，不碰真实的材料根目录（材料索引也在里面）。
"""

from datetime import date

import pytest

from core.models import MaterialCategory, MaterialRecord, PersonalProfile, TravelHistoryEntry
from core.profile_storage import load_personal_profile, save_personal_profile
from core.storage import RecordIdConflictError, load_material_records, save_material_record
from core.uploads import UploadConflictError, save_uploaded_file


def test_save_material_record_then_load_it_back(tmp_path):
    record = MaterialRecord(
        id="new-passport-page",
        category=MaterialCategory.PASSPORT_SCAN,
        type="护照签证页",
        belongs_to="test-application",
        obtained_date=date(2026, 9, 22),
    )
    save_material_record(tmp_path, record)

    loaded = load_material_records(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].id == "new-passport-page"


def test_save_material_record_rejects_duplicate_id(tmp_path):
    record = MaterialRecord(
        id="dup",
        category=MaterialCategory.PASSPORT_SCAN,
        type="护照签证页",
        belongs_to="test-application",
    )
    save_material_record(tmp_path, record)

    with pytest.raises(RecordIdConflictError):
        save_material_record(tmp_path, record)


def test_save_uploaded_file_returns_relative_path(tmp_path):
    file_ref = save_uploaded_file(
        materials_root=tmp_path,
        category="passport_scan",
        record_id="new-passport-page",
        original_filename="scan.jpg",
        content=b"fake image bytes",
    )
    assert file_ref == "passport_scan/new-passport-page.jpg"
    assert (tmp_path / file_ref).read_bytes() == b"fake image bytes"


def test_save_uploaded_file_refuses_to_overwrite(tmp_path):
    save_uploaded_file(tmp_path, "passport_scan", "dup", "a.jpg", b"first")
    with pytest.raises(UploadConflictError):
        save_uploaded_file(tmp_path, "passport_scan", "dup", "a.jpg", b"second")


def test_personal_profile_round_trip_with_travel_history(tmp_path):
    profile = PersonalProfile(
        full_name="张三",
        travel_history=[
            TravelHistoryEntry(country="日本", entry_date=date(2026, 5, 1), exit_date=date(2026, 5, 10))
        ],
    )
    save_personal_profile(tmp_path, profile)

    loaded = load_personal_profile(tmp_path)
    assert loaded.full_name == "张三"
    assert len(loaded.travel_history) == 1
    assert loaded.travel_history[0].country == "日本"


def test_personal_profile_missing_file_returns_empty_profile(tmp_path):
    profile = load_personal_profile(tmp_path)
    assert profile.travel_history == []
