#!/usr/bin/env python3
"""假的 Claude Code CLI，给 spec 004 的测试用：按 FAKE_CLAUDE_MODE 输出预设的 stream-json，绝不联网。

- FAKE_CLAUDE_MODE：ok（默认）/ slow（启动后一直等，用来测 409 和取消）/ error（结果是错误）/ crash（直接退出）
- FAKE_CLAUDE_ARGV：设了就把本次收到的参数写进这个文件，测试用来检查命令行
- FAKE_CLAUDE_KIND：设了就把环境变量 PA_AGENT_KIND 写进这个文件
"""

import json
import os
import sys
import time

args = sys.argv[1:]
if os.environ.get("FAKE_CLAUDE_ARGV"):
    with open(os.environ["FAKE_CLAUDE_ARGV"], "w", encoding="utf-8") as f:
        json.dump(args, f, ensure_ascii=False)

if os.environ.get("FAKE_CLAUDE_KIND"):  # 记下网页任务的类型环境变量（spec 007：只有 trip_extract 能读材料）
    with open(os.environ["FAKE_CLAUDE_KIND"], "w", encoding="utf-8") as f:
        f.write(os.environ.get("PA_AGENT_KIND", ""))

if args == ["--version"]:
    print("9.9.9 (Fake Claude)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    # 真 CLI 的输出里有邮箱等信息，这里也放一个，测试确认它不会被传到页面
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "someone@example.com"}))
    sys.exit(0)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
out({"type": "system", "subtype": "init", "session_id": "sess-1"})
if mode == "slow":
    time.sleep(30)
    sys.exit(0)
if mode == "crash":
    print("boom", file=sys.stderr)
    sys.exit(3)
out({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "mcp__personal-assistant__list_guides", "input": {}}]}})
for piece in ["一共有", " 6 份攻略。"]:
    out({"type": "stream_event", "event": {"type": "content_block_delta",
                                           "delta": {"type": "text_delta", "text": piece}}})
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "一共有 6 份攻略。"}]}})
if mode == "error":
    out({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
         "result": "超出用量上限", "session_id": "sess-1", "total_cost_usd": 5.01})
else:
    out({"type": "result", "subtype": "success", "is_error": False, "result": "一共有 6 份攻略。",
         "session_id": "sess-1", "total_cost_usd": 0.25})
