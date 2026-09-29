"""把填表引擎的页面脚本复制进浏览器插件（specs/006-browser-extension）。

插件目录要能直接"加载已解压的扩展程序"，不能引用插件目录外的文件，所以 extension/engine/ 下放一份复制品。
引擎只在 src/form_engine/ 里改；改完运行：

    uv run python scripts/build_extension.py

测试（tests/unit/test_extension_files.py）会检查两边是否一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "form_engine"
OUT = ROOT / "extension" / "engine"

HEADER = "// 由 scripts/build_extension.py 从 src/form_engine/{name} 生成，不要直接改这个文件。\n"
# 插件里的填写计划由后台先放进 window.__paPlan，用完立即删掉（计划里的值本来就要写进页面格子）
PLAN_FROM_WINDOW = "(() => { const p = window.__paPlan || []; delete window.__paPlan; return p; })()"


def built_files() -> dict[str, str]:
    scan = (SRC / "scan.js").read_text(encoding="utf-8")
    fill = (SRC / "fill.js").read_text(encoding="utf-8")
    if fill.count("__PLAN__") != 1:
        raise SystemExit("src/form_engine/fill.js 里的 __PLAN__ 占位词应该正好出现一次")
    return {
        "scan.js": HEADER.format(name="scan.js") + scan,
        "fill.js": HEADER.format(name="fill.js") + fill.replace("__PLAN__", PLAN_FROM_WINDOW),
        "read.js": HEADER.format(name="read.js") + (SRC / "read.js").read_text(encoding="utf-8"),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in built_files().items():
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"✓ extension/engine/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
