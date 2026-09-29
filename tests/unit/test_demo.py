"""试用模式：`uv run youtiao --demo` 用临时文件夹里的虚构资料启动，不碰真实材料根目录。"""

from datetime import date

from fastapi.testclient import TestClient

import api.app as app_module
import config
from api import launcher
from api.demo import build_demo_root

LOCAL = {"Host": "127.0.0.1:8000"}


def test_env_overrides_materials_root(tmp_path, monkeypatch):
    monkeypatch.setenv(config.MATERIALS_ROOT_ENV, str(tmp_path))
    assert config.get_materials_root() == tmp_path.resolve()
    monkeypatch.delenv(config.MATERIALS_ROOT_ENV)
    assert config.get_materials_root() != tmp_path.resolve()


def test_demo_root_has_profile_materials_and_example_track(tmp_path, monkeypatch):
    root = build_demo_root(tmp_path / "demo", date(2026, 9, 29))
    monkeypatch.setenv(config.MATERIALS_ROOT_ENV, str(root))
    c = TestClient(app_module.app)
    assert c.get("/api/personal-profile", headers=LOCAL).json()["identity"]["surname"] == "ZHANG"
    from api.demo import EXAMPLES
    assert len(c.get("/api/materials", headers=LOCAL).json()) == len(list((EXAMPLES / "records").glob("*.yaml")))
    tracks = c.get("/api/tracks", headers=LOCAL).json()
    assert [t["title"] for t in tracks] == ["示例：申根短期旅游签证"]


def test_launcher_demo_sets_env(monkeypatch, tmp_path):
    monkeypatch.delenv(config.MATERIALS_ROOT_ENV, raising=False)
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix: str(tmp_path / "d"))
    launcher.main(["--demo", "--no-browser"])
    import os
    assert os.environ[config.MATERIALS_ROOT_ENV] == str(tmp_path / "d")
    assert (tmp_path / "d" / "personal-profile.yaml").is_file()
    # 是 launcher 自己设的，直接删掉（用 monkeypatch.delenv 的话测试结束时反而会被"恢复"回来，影响后面的测试）
    os.environ.pop(config.MATERIALS_ROOT_ENV)
