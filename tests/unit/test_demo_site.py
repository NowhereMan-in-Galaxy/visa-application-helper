"""在线演示站（docs/demo/site.md）：能生成，路径都是相对的，演示脚本没被改坏，数据里没有本机路径。"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_builder():
    spec = importlib.util.spec_from_file_location("build_demo_site", REPO / "scripts" / "build_demo_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_site_builds(tmp_path, monkeypatch):
    import config
    monkeypatch.delenv(config.MATERIALS_ROOT_ENV, raising=False)
    b = load_builder()
    site = tmp_path / "_site"
    b.build(site)
    monkeypatch.delenv(config.MATERIALS_ROOT_ENV, raising=False)  # build() 设了环境变量，别影响后面的测试

    assert (site / "index.html").is_file() and (site / ".nojekyll").is_file()
    html = (site / "guides.html").read_text(encoding="utf-8")
    assert '<script src="assets/demo-shim.js"></script>' in html and '"/assets/' not in html
    assert (site / "assets" / "demo-shim.js").read_text(encoding="utf-8") == (REPO / "docs/demo/demo-shim.js").read_text(encoding="utf-8")
    for js in (site / "assets").glob("*.js"):
        if js.name != "demo-shim.js":
            assert '"/api/' not in js.read_text(encoding="utf-8"), js.name

    data = site / "data"
    guides = json.loads((data / "guides.json").read_text(encoding="utf-8"))
    for g in guides:
        assert (data / b.data_file(f"guides/{g['id']}")).is_file()
    track = json.loads((data / "tracks.json").read_text(encoding="utf-8"))[0]
    assert json.loads((data / b.data_file(f"tracks/{track['id']}")).read_text(encoding="utf-8"))["trip"]["purpose"] == "Tourism"
    assert json.loads((data / "agent_2fstatus.json").read_text(encoding="utf-8"))["available"] is False
    assert json.loads((data / "export-locations.json").read_text(encoding="utf-8")) == []
    everything = "".join(p.read_text(encoding="utf-8") for p in data.iterdir())
    assert str(Path.home()) not in everything


def test_data_file_matches_the_shim():
    b = load_builder()
    assert b.data_file("tracks") == "tracks.json"
    assert b.data_file("fill-helper?track_id=a-1") == "fill-helper_3ftrack_5fid_3da-1.json"
    shim = (REPO / "docs/demo/demo-shim.js").read_text(encoding="utf-8")
    assert '/[A-Za-z0-9.-]/' in shim and 'u.pathname.indexOf("/api/")' in shim
