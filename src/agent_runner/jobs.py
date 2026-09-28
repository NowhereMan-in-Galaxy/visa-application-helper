"""后台任务：启动 / 取消 Agent 子进程，把它的 stream-json 输出翻译成页面能用的事件（spec 004"接口"）。

用线程而不是 asyncio：uvicorn 和测试用的 TestClient 都能稳定运行，页面那头的 SSE 用同步生成器读事件。
同一时间只允许一个任务在跑（第二个返回 409），因为每个任务都会占用用户的订阅额度，也可能在操作同一个浏览器。
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

from config import REPO_ROOT

from agent_runner import cli

# 工具名 → 页面上显示的进度说明。没列出的工具显示原名。
TOOL_LABELS = {
    "list_guides": "查看攻略库",
    "get_guide": "读取攻略",
    "list_tracks": "查看我的办事",
    "get_track": "读取办事进度",
    "get_personal_profile": "读取基本信息",
    "get_profile_gaps": "检查基本信息缺口",
    "validate_community": "校验共享内容",
    "Read": "阅读项目文件",
    "ToolSearch": "准备工具",
}

MAX_KEPT_JOBS = 20


class JobConflictError(Exception):
    """已经有任务在跑。"""


@dataclass
class Job:
    id: str
    kind: str
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    cancelled: bool = False
    proc: subprocess.Popen | None = None
    cond: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, type_: str, **data) -> None:
        with self.cond:
            self.events.append({"type": type_, **data})
            if type_ in ("done", "error"):
                self.finished = True
            self.cond.notify_all()


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _tool_label(name: str) -> str:
    short = name.removeprefix(cli.MCP_PREFIX)
    return TOOL_LABELS.get(short, short)


def translate(line: dict, state: dict) -> list[tuple[str, dict]]:
    """把 stream-json 的一行翻译成 0 到多个页面事件。纯函数，方便单测。

    state 在同一个任务内共享，用来避免重复输出文字：开了 --include-partial-messages 后，
    文字会先以 text_delta 一小段一小段到达，随后整条 assistant 消息里还会再出现一遍完整文字。
    """
    out: list[tuple[str, dict]] = []
    kind = line.get("type")
    if kind == "system" and line.get("subtype") == "init":
        state["session_id"] = line.get("session_id")
        out.append(("progress", {"text": "Agent 已启动"}))
    elif kind == "stream_event":
        ev = line.get("event") or {}
        delta = ev.get("delta") or {}
        if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            state["streamed"] = True
            out.append(("text", {"text": delta.get("text", "")}))
    elif kind == "assistant":
        for block in (line.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                out.append(("progress", {"text": "正在" + _tool_label(block.get("name", ""))}))
            elif block.get("type") == "text" and not state.get("streamed"):
                out.append(("text", {"text": block.get("text", "")}))
        state["streamed"] = False
    elif kind == "result":
        state["session_id"] = line.get("session_id") or state.get("session_id")
        usage = {"session_id": state.get("session_id"), "cost_usd": line.get("total_cost_usd")}
        if line.get("is_error"):
            out.append(("error", {"text": str(line.get("result") or line.get("subtype") or "Agent 出错"), **usage}))
        else:
            out.append(("done", usage))
    return out


def _run(job: Job, cmd: list[str]) -> None:
    state: dict = {}
    try:
        job.proc = subprocess.Popen(
            cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
        )
    except OSError as e:
        job.emit("error", text=f"启动 Agent 失败：{e}")
        return
    assert job.proc.stdout is not None
    for raw in job.proc.stdout:
        raw = raw.strip()
        if not raw:
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for type_, data in translate(line, state):
            job.emit(type_, **data)
    job.proc.wait()
    if not job.finished:
        if job.cancelled:
            job.emit("error", text="已取消", session_id=state.get("session_id"))
        else:
            err = (job.proc.stderr.read() if job.proc.stderr else "").strip()[-300:]
            job.emit("error", text=f"Agent 意外退出（{job.proc.returncode}）{('：' + err) if err else ''}",
                     session_id=state.get("session_id"))


def start(kind: str, prompt: str, *, session_id: str | None = None) -> Job:
    """启动一个任务；已有任务在跑时抛 JobConflictError。"""
    cmd = cli.build_command(kind, prompt, session_id=session_id)
    with _lock:
        if any(not j.finished for j in _jobs.values()):
            raise JobConflictError
        job = Job(id=uuid4().hex[:12], kind=kind)
        _jobs[job.id] = job
        while len(_jobs) > MAX_KEPT_JOBS:
            oldest = next(iter(_jobs))
            if not _jobs[oldest].finished:
                break
            del _jobs[oldest]
    threading.Thread(target=_run, args=(job, cmd), daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def cancel(job: Job) -> None:
    job.cancelled = True
    proc = job.proc
    if proc is None or proc.poll() is not None:
        if not job.finished:
            job.emit("error", text="已取消")
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def iter_events(job: Job, *, keepalive: float = 15.0):
    """按顺序逐个吐出事件，直到 done / error；期间没事件时每隔 keepalive 秒吐一个 None（给 SSE 保活）。"""
    i = 0
    while True:
        with job.cond:
            if i >= len(job.events) and not job.finished:
                job.cond.wait(timeout=keepalive)
            batch = job.events[i:]
            finished = job.finished
        if not batch and not finished:
            yield None
            continue
        for ev in batch:
            yield ev
        i += len(batch)
        if finished and i >= len(job.events):
            return


def wait_finished(job: Job, timeout: float = 10.0) -> bool:
    """测试用：等任务结束。"""
    deadline = time.monotonic() + timeout
    with job.cond:
        while not job.finished:
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            job.cond.wait(timeout=left)
    return True
