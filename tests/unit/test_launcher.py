"""`uv run youtiao`：一条命令启动本地服务并打开浏览器。"""

from api import launcher


def test_launcher_defaults(monkeypatch):
    calls = {}
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    opened = []
    monkeypatch.setattr(launcher.threading, "Timer", lambda delay, fn, args: type("T", (), {"start": lambda self: opened.append(args[0])})())
    launcher.main([])
    assert calls["app"] == "api.app:app" and calls["host"] == "127.0.0.1" and calls["port"] == 8000
    assert calls["reload"] is False
    assert opened == ["http://127.0.0.1:8000/"]


def test_launcher_options(monkeypatch):
    calls = {}
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kw: calls.update(kw))
    monkeypatch.setattr(launcher.threading, "Timer", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该打开浏览器")))
    launcher.main(["--no-browser", "--port", "8123", "--reload"])
    assert calls["port"] == 8123 and calls["reload"] is True and calls["reload_dirs"]
