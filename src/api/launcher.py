"""一条命令启动本地服务并打开浏览器：`uv run youtiao`。

浏览器插件固定连 http://127.0.0.1:8000（specs/006），所以默认端口是 8000；只有 127.0.0.1 能访问。
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

SRC = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="youtiao", description="启动有条有理的本地服务，并在浏览器里打开")
    parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000；浏览器插件只认 8000）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="改了代码自动重启（开发时用）")
    parser.add_argument("--demo", action="store_true", help="试用模式：用一套虚构资料启动，不碰你的真实资料")
    args = parser.parse_args(argv)

    if args.demo:
        import os
        import tempfile
        from datetime import date

        import config
        from api.demo import build_demo_root

        root = build_demo_root(Path(tempfile.mkdtemp(prefix="youtiao-demo-")), date.today())
        os.environ[config.MATERIALS_ROOT_ENV] = str(root)  # 本进程和它调起的 Agent 都用这套虚构资料
        print(f"试用模式：资料都是虚构的，放在 {root}")

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    print(f"有条有理：{url}　按 Ctrl+C 停止")
    uvicorn.run(
        "api.app:app", host="127.0.0.1", port=args.port,
        reload=args.reload, reload_dirs=[str(SRC)] if args.reload else None,
    )
