"""生成在线演示站（docs/demo/site.md）：把网页和试用模式的虚构资料导出成一个不需要后台的静态网站。

    uv run python scripts/build_demo_site.py _site

做三件事：
1. 在临时文件夹里准备试用模式的虚构资料（和 `uv run youtiao --demo` 同一套），用测试客户端请求页面会用到的
   每一个 GET 接口，把返回结果存成 data/*.json；
2. 复制 web/，把以 / 开头的路径改成相对路径（GitHub Pages 的网址多一层 /<仓库名>/）；
3. 每个页面最前面加上 docs/demo/demo-shim.js：读 data/*.json 代替后台，修改操作回"只能看"。

导出的内容里如果出现本机绝对路径，直接报错，不生成。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import config  # noqa: E402
from api.demo import build_demo_root  # noqa: E402

PAGES = ("guides.html", "my.html", "travel.html", "fill-helper.html", "assist.html")
ABSOLUTE = re.compile(r"""(["'(])/(assets/|api/|(?:%s)\b)""" % "|".join(re.escape(p) for p in PAGES))
# 演示里用不了、或会暴露构建机器信息的接口，给一个固定的回答
FIXED = {
    "agent/status": {"available": False, "cli_path": None, "cli_version": None, "auth_method": None, "api_key_env": False},
    "export-locations": [],
    "guide-drafts": [],
}


def data_file(key: str) -> str:
    """和 demo-shim.js 的 dataFile() 一致。"""
    return "".join(c if re.match(r"[A-Za-z0-9.-]", c) else "_%x" % ord(c) for c in key) + ".json"


def collect(client) -> dict[str, object]:
    def get(key: str):
        r = client.get("/api/" + key, headers={"Host": "127.0.0.1:8000"})
        if r.status_code != 200:
            raise SystemExit(f"GET /api/{key} 返回 {r.status_code}：{r.text[:200]}")
        return r.json()

    out: dict[str, object] = dict(FIXED)
    for key in ("guides", "tracks", "materials", "materials/usage", "material-types",
                "personal-profile", "personal-profile/fields", "fill-helper", "guide-types"):
        out[key] = get(key)
    for g in out["guides"]:
        out[f"guides/{g['id']}"] = get(f"guides/{g['id']}")
    for t in out["tracks"]:
        out[f"tracks/{t['id']}"] = get(f"tracks/{t['id']}")
        out[f"fill-helper?track_id={t['id']}"] = get(f"fill-helper?track_id={t['id']}")
    for form in sorted((config.COMMUNITY_DIR / "forms").glob("*.yaml")):
        out[f"forms/{form.stem}"] = get(f"forms/{form.stem}")
    return out


def build(dest: Path) -> None:
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="youtiao-site-") as tmp:
        root = build_demo_root(Path(tmp) / "demo", date.today())
        os.environ[config.MATERIALS_ROOT_ENV] = str(root)
        import api.app as app_module

        data = collect(TestClient(app_module.app))
        leaks = [k for k, v in data.items() if tmp in json.dumps(v) or str(Path.home()) in json.dumps(v)]
        if leaks:
            raise SystemExit(f"导出的数据里有本机路径，不生成：{leaks}")

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REPO / "web", dest)
    for f in list(dest.rglob("*.html")) + list(dest.rglob("*.js")) + list(dest.rglob("*.css")):
        text = f.read_text(encoding="utf-8")
        text = ABSOLUTE.sub(r"\1\2", text)
        if f.suffix == ".html":
            text = text.replace("<head>", '<head>\n<script src="assets/demo-shim.js"></script>', 1)
        f.write_text(text, encoding="utf-8")
    # 演示脚本最后放进去：它自己要认 /api/ 路径，不能被上面的相对路径替换改掉
    shutil.copy(REPO / "docs" / "demo" / "demo-shim.js", dest / "assets" / "demo-shim.js")
    (dest / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=guides.html">'
        '<title>有条有理 · 在线演示</title><a href="guides.html">打开在线演示</a>\n', encoding="utf-8")
    (dest / ".nojekyll").write_text("", encoding="utf-8")  # 让 GitHub Pages 原样发布，不经过 Jekyll
    out = dest / "data"
    out.mkdir()
    for key, value in data.items():
        (out / data_file(key)).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    print(f"演示站已生成：{dest}（{len(data)} 份数据）")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "_site").resolve())
