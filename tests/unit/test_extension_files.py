"""spec 006：浏览器插件的文件（清单、固定 ID、引擎复制品），以及插件的填写流程在真实 Chrome 里跑一遍。"""

import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from api.extension import EXTENSION_ID
from form_engine import match

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
FIXTURES = ROOT / "tests" / "fixtures" / "forms"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# GitHub Actions 的 Linux 机器上，无界面 Chrome 要关掉沙盒才能启动
LINUX_SANDBOX = ["--no-sandbox"] if sys.platform.startswith("linux") else []
sys.path.insert(0, str(ROOT / "scripts"))
import build_extension  # noqa: E402


def manifest():
    return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_permissions_are_minimal():
    m = manifest()
    assert m["manifest_version"] == 3
    assert sorted(m["permissions"]) == ["activeTab", "scripting", "sidePanel", "storage", "tabs"]
    assert m["host_permissions"] == ["http://127.0.0.1:8000/*"]
    assert sorted(m["optional_host_permissions"]) == ["http://*/*", "https://*/*"]
    assert (EXT / m["background"]["service_worker"]).is_file() and (EXT / "sidepanel.html").is_file()
    # 侧边栏只在点了图标的标签页里打开（不在清单里写全局 default_path）
    assert "side_panel" not in m
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert "openPanelOnActionClick: false" in bg and "setOptions({ tabId: tab.id" in bg


def test_fixed_key_gives_the_allowed_id():
    der = base64.b64decode(manifest()["key"])
    digest = hashlib.sha256(der).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(c, 16)) for c in digest) == EXTENSION_ID


def test_engine_copies_are_in_sync():
    for name, text in build_extension.built_files().items():
        assert (EXT / "engine" / name).read_text(encoding="utf-8") == text, (
            f"extension/engine/{name} 过期了：运行 uv run python scripts/build_extension.py")


def test_no_private_key_in_repo():
    for p in EXT.rglob("*"):
        if p.is_file():
            assert "PRIVATE KEY" not in p.read_text(encoding="utf-8", errors="ignore"), p


@pytest.mark.skipif(not Path(CHROME).exists() and not shutil.which("google-chrome"), reason="没有 Chrome")
def test_extension_flow_in_headless_chrome(tmp_path):
    """按 background.js 的顺序：scan.js → 计划 → window.__paPlan + fill.js → window.__paMarks + mark.js。"""
    from core.models import PersonalProfile

    profile = PersonalProfile.model_validate({
        "identity": {"surname": "EXAMPLE", "sex": "female", "nationality": "中国"},
        "contact": {"home_address": {"city": "Testville"}, "email": "sample@example.com"},
    })
    fields = match.expand_scan((FIXTURES / "generic-form.scan.json").read_text(encoding="utf-8"))
    plan = match.plan(fields, profile, match.default_dictionary())
    marks = [{"i": x["i"], "why": "资料里没有"} for x in plan["missing"]] + [{"i": x["i"], "why": "没认出"} for x in plan["unmatched"]]

    engine = {n: (EXT / "engine" / n).read_text(encoding="utf-8").strip() for n in ("scan.js", "fill.js", "mark.js")}
    js = (
        f"var header = JSON.parse({engine['scan.js']});"
        "var scanText = window.__paScanText;"
        f"window.__paPlan = {json.dumps(plan['ops'], ensure_ascii=False)};"
        f"var counts = JSON.parse({engine['fill.js']});"
        f"window.__paMarks = {json.dumps(marks, ensure_ascii=False)};"
        f"var marked = JSON.parse({engine['mark.js']});"
        'document.getElementById("pa-out").textContent = JSON.stringify({header, scanText, counts, marked,'
        ' planLeft: "__paPlan" in window, marksLeft: "__paMarks" in window,'
        ' red: document.querySelectorAll("[style*=\'192, 57, 43\'], [style*=\'#c0392b\']").length,'
        ' surname: document.querySelector("[name=surname]").value,'
        ' city: document.querySelector("[name=homeCity]").value,'
        ' nat: document.querySelector("[name=nationality]").value,'
        ' sex: (document.querySelector("[name=sex]:checked") || {}).value});'
    )
    page = tmp_path / "page.html"
    src = (FIXTURES / "generic-form.html").read_text(encoding="utf-8")
    page.write_text(src.replace("</body>", f'<pre id="pa-out"></pre><script>{js}</script></body>'), encoding="utf-8")
    exe = CHROME if Path(CHROME).exists() else shutil.which("google-chrome")
    dom = subprocess.run([exe, "--headless=new", "--disable-gpu", *LINUX_SANDBOX, "--dump-dom", page.as_uri()],
                         capture_output=True, text=True, timeout=60).stdout
    out = json.loads(html.unescape(re.search(r'<pre id="pa-out">(.*?)</pre>', dom, re.S).group(1)))

    assert out["header"]["count"] == 25
    # 插件扫描出的格子和测试表单的扫描记录一致（新版多了"会刷新页面"一项，这个表单里都是 0）
    assert [f[:8] for f in json.loads(out["scanText"])["f"]] == [f[:8] for f in json.loads(
        (FIXTURES / "generic-form.scan.json").read_text(encoding="utf-8"))["f"]]
    assert out["counts"] == {"filled": len(plan["ops"]), "skipped": 0, "gone": 0, "already": 0}
    assert out["surname"] == "EXAMPLE" and out["city"] == "Testville" and out["nat"] == "CN" and out["sex"] == "F"
    assert out["marked"]["marked"] == len(marks) and out["red"] == len(marks)
    assert out["planLeft"] is False and out["marksLeft"] is False  # 计划用完就删


def test_watch_script_only_counts_fields():
    """第三版：冒出新格子时再填。watch.js 在插件隔离环境里跑，不读格子内容；每一轮标红前先清掉上一轮的红框。"""
    watch = (EXT / "engine" / "watch.js").read_text(encoding="utf-8")
    assert ".value" not in watch and "fields-appeared" in watch and "WeakSet" in watch
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert "files: ['engine/watch.js'], world: 'ISOLATED'" in bg and "MAX_WATCH_FILLS" in bg
    assert "data-pa-red" in (EXT / "engine" / "mark.js").read_text(encoding="utf-8")

