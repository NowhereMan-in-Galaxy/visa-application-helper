"""材料索引的位置：必须在材料根目录下，不能回到仓库里（个人信息不进仓库，见 AGENTS.md 第 3 条）。"""

import config


def test_index_dir_follows_materials_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path / "root")
    assert config.get_materials_index_dir() == tmp_path / "root" / "index"


def test_repo_has_no_material_index_constant():
    # 旧的 MATERIALS_INDEX_DIR 指向仓库里的 materials_index/，已经废弃
    assert not hasattr(config, "MATERIALS_INDEX_DIR")
