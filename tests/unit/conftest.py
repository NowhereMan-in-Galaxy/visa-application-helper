"""几个测试文件共用的 fixture。"""

import stat
from pathlib import Path

import pytest

from agent_runner import jobs

FAKE = Path(__file__).with_name("fake_claude.py")


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    """用 fake_claude.py 代替真的 Claude Code（spec 004）；返回记录本次命令行参数的文件路径。"""
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PA_AGENT_CLI", str(FAKE))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(argv_file))
    yield argv_file
    # 别让没结束的任务影响下一个测试
    for job in list(jobs._jobs.values()):
        if not job.finished:
            jobs.cancel(job)
            jobs.wait_finished(job)
    jobs._jobs.clear()
