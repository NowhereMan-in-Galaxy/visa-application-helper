"""界面里的 Agent 做的修改：撤销记录和基本信息提议（spec 004 第 3 步）。

- ② 类（改自己的办事进度）：只有从网页调起时（环境变量 PA_AGENT_UI=1）才记录。每次写之前先存一份这件办事的
  原文件，撤销就是放回原文件；如果之后这件办事又被改过（文件和记录里的"改完后"对不上），拒绝撤销，免得冲掉新的修改。
- ③ 类（改基本信息）：Agent 只能"提议"，写进提议文件；用户在页面上点确认，才调用正常的写入逻辑。

记录都放在材料根目录的 agent/ 下（被 git 忽略）。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.models import describe_personal_profile
from core.profile_storage import preview_profile_fields, update_profile_fields
from core.tracks import tracks_dir

UI_ENV = "PA_AGENT_UI"
MAX_ACTIVITIES = 200


class ActivityError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def activity_path(root: Path) -> Path:
    return root / "agent" / "activity.jsonl"


def proposals_path(root: Path) -> Path:
    return root / "agent" / "profile-proposals.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


# ---------- ② 撤销记录 ----------


def read_activities(root: Path) -> list[dict]:
    path = activity_path(root)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_activities(root: Path, entries: list[dict]) -> None:
    path = activity_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries[-MAX_ACTIVITIES:]), encoding="utf-8")


def _name_in_view(view: dict, kind: str, item_id: str) -> str:
    if kind in ("step", "steps"):
        return next((s.get("title") for s in view.get("steps", []) if s.get("id") == item_id), item_id)
    if kind in ("requirement", "requirements"):
        return next((r.get("name") for r in view.get("requirements", []) if r.get("id") == item_id), item_id)
    return item_id


def summarize(tool: str, args: dict, view: dict) -> str:
    """页面上显示的一句话，例如"已勾上：递交材料"。"""
    if tool == "set_step_done":
        return ("已勾上：" if args.get("done") else "已取消勾选：") + _name_in_view(view, "step", args.get("step_id", ""))
    if tool == "set_fact":
        q = next((f.get("question") for f in view.get("facts", []) if f.get("key") == args.get("fact")), args.get("fact"))
        return f"已回答：{q} → {args.get('value')}" if args.get("value") is not None else f"已清除回答：{q}"
    if tool == "set_hidden":
        return ("已隐藏：" if args.get("hidden") else "已恢复：") + _name_in_view(view, args.get("kind", ""), args.get("item_id", ""))
    if tool == "set_note":
        return ("已写备注：" if args.get("note") else "已删除备注：") + _name_in_view(view, args.get("kind", ""), args.get("item_id", ""))
    if tool == "add_custom_step":
        return f"已加步骤：{args.get('title')}"
    if tool == "add_custom_material":
        return f"已加材料：{args.get('name')}"
    if tool == "confirm_match":
        return ("已确认使用：" if args.get("confirmed") else "已取消确认：") + _name_in_view(view, "requirement", args.get("requirement_id", ""))
    if tool == "add_pitfall":
        text = str(args.get("text", ""))
        return "已记避坑点：" + (text[:24] + "…" if len(text) > 24 else text)
    return f"已修改（{tool}）"


def record_track_write(root: Path, tool: str, args: dict, fn):
    """执行一次改办事进度的操作；从网页调起时顺便记下撤销信息。返回 fn() 的结果。"""
    if os.environ.get(UI_ENV) != "1":
        return fn()
    path = tracks_dir(root) / f"{args['track_id']}.yaml"
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    result = fn()
    after = path.read_text(encoding="utf-8") if path.is_file() else None
    if after == before:
        return result
    entries = read_activities(root)
    entries.append({
        "id": uuid4().hex[:12],
        "time": _now(),
        "tool": tool,
        "track_id": args["track_id"],
        "summary": summarize(tool, args, result if isinstance(result, dict) else {}),
        "before": before,
        "after_sha": _sha(after),
    })
    _write_activities(root, entries)
    return result


def undo(root: Path, activity_id: str) -> dict:
    entries = read_activities(root)
    entry = next((e for e in entries if e.get("id") == activity_id), None)
    if entry is None:
        raise ActivityError("找不到这条修改记录（可能太久了）", 404)
    if entry.get("undone"):
        raise ActivityError("已经撤销过了")
    path = tracks_dir(root) / f"{entry['track_id']}.yaml"
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if _sha(current) != entry.get("after_sha"):
        raise ActivityError("这件事之后又改过，不能直接撤销了，请在页面上手动改回来")
    if entry.get("before") is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(entry["before"], encoding="utf-8")
    entry["undone"] = True
    _write_activities(root, entries)
    return {"id": activity_id, "track_id": entry["track_id"], "summary": entry["summary"]}


# ---------- ③ 基本信息提议 ----------


def _labels() -> dict[str, str]:
    out = {}
    for g in describe_personal_profile():
        for f in g["fields"]:
            out[f"{g['key']}.{f['key']}"] = f"{g['label']} › {f['label']}"
    return out


def read_proposals(root: Path) -> list[dict]:
    try:
        return json.loads(proposals_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _write_proposals(root: Path, items: list[dict]) -> None:
    path = proposals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _show(value):
    """确认卡片上显示的值：列表写"N 条"，对象不会出现在这里（已经拆到每一格）。"""
    if isinstance(value, list):
        if all(isinstance(x, (str, int, float)) for x in value):
            return "、".join(map(str, value)) or None
        return f"{len(value)} 条"
    return value


def _leaf_changes(path: str, before, after, out: list[dict]) -> None:
    """对象逐格比较，只留真正变了的那一格（2026-09-29 项目主：只改工作电话，卡片却把整个单位的 JSON 都列了出来）。"""
    if isinstance(before, dict) and isinstance(after, dict):
        for k in after:
            _leaf_changes(f"{path}.{k}", before.get(k), after.get(k), out)
        return
    if before != after:
        out.append({"field": path.split(".", 1)[1], "path": path, "before": _show(before), "after": _show(after)})


def propose_profile_update(root: Path, group: str, changes: dict) -> dict:
    """校验并记下一条提议，不改基本信息。值没有变化时不记。"""
    from form_engine.match import profile_leaves

    changed = preview_profile_fields(root, group, changes)
    if not changed:
        return {"proposal_id": None, "changed": []}
    leaves = profile_leaves()
    labels = _labels()
    cells: list[dict] = []
    for c in changed:
        _leaf_changes(f"{group}.{c['field']}", c["before"], c["after"], cells)
    for c in cells:
        leaf = leaves.get(c["path"])
        c["label"] = leaf.label if leaf else labels.get(c["path"], c["field"])
    item = {
        "id": uuid4().hex[:12],
        "time": _now(),
        "group": group,
        "changes": changes,
        "changed": cells,
    }
    _write_proposals(root, read_proposals(root) + [item])
    return {"proposal_id": item["id"], "changed": item["changed"]}


def propose_trip_update(root: Path, track_id: str, changes: dict) -> dict:
    """提议改一件办事的行程信息（spec 007），和 propose_profile_update 一样要用户在页面上确认。

    group 记为 "trip"，另存 track_id；确认时写进这件办事，不写基本信息。
    """
    from core.tracks import load_track
    from core.trip import merge_trip
    from form_engine.match import profile_leaves

    track = load_track(root, track_id)  # 不存在抛 TrackNotFoundError
    before = track.trip.model_dump(mode="json")
    after = merge_trip(track.trip, changes).model_dump(mode="json")  # 不合法抛 ValidationError
    cells: list[dict] = []
    for key in changes:
        _leaf_changes(f"trip.{key}", before.get(key), after.get(key), cells)
    if not cells:
        return {"proposal_id": None, "changed": []}
    leaves = profile_leaves()
    for c in cells:
        leaf = leaves.get(c["path"])
        c["label"] = leaf.label if leaf else c["field"]
    item = {"id": uuid4().hex[:12], "time": _now(), "group": "trip", "track_id": track_id,
            "changes": changes, "changed": cells}
    _write_proposals(root, read_proposals(root) + [item])
    return {"proposal_id": item["id"], "changed": cells}


def _pop_proposal(root: Path, proposal_id: str) -> dict:
    items = read_proposals(root)
    item = next((p for p in items if p.get("id") == proposal_id), None)
    if item is None:
        raise ActivityError("找不到这条提议（可能已经处理过了）", 404)
    _write_proposals(root, [p for p in items if p.get("id") != proposal_id])
    return item


def confirm_proposal(root: Path, proposal_id: str) -> dict:
    item = next((p for p in read_proposals(root) if p.get("id") == proposal_id), None)
    if item is None:
        raise ActivityError("找不到这条提议（可能已经处理过了）", 404)
    if item.get("group") == "trip":
        from core.tracks import load_track, save_track
        from core.trip import merge_trip

        track = load_track(root, item["track_id"])
        track.trip = merge_trip(track.trip, item["changes"])  # 校验不过会抛错，提议保留
        save_track(root, track)
        changed = item["changed"]
    else:
        _, changed = update_profile_fields(root, item["group"], item["changes"])  # 校验不过会抛错，提议保留
    _pop_proposal(root, proposal_id)
    return {"id": proposal_id, "changed": changed}


def reject_proposal(root: Path, proposal_id: str) -> dict:
    _pop_proposal(root, proposal_id)
    return {"id": proposal_id}


# ---------- 填表插件的"让 Agent 补填"（spec 006 第二版） ----------

MAX_FORM_FILLS = 50
MAX_FILL_VALUE = 2000


def form_fills_path(root: Path) -> Path:
    return root / "agent" / "form-fills.jsonl"


def read_form_fills(root: Path) -> list[dict]:
    path = form_fills_path(root)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _profile_paths() -> set[str]:
    """基本信息里所有字段的路径：单值字段（含嵌套对象）和列表字段本身（例如 identity.other_names）。"""
    from form_engine.match import profile_leaves

    paths = set(profile_leaves())
    for g in describe_personal_profile():
        paths.update(f"{g['key']}.{f['key']}" for f in g["fields"])
    return paths


def submit_form_fills(root: Path, fills: list[dict], learn: list[dict] | None = None) -> dict:
    """记下 Agent 判断好的"哪一格填什么"，由后台任务推给插件去填。不碰官网，也不改基本信息。

    fills：[{"i": 格子编号, "value": 文字}]；learn：[{"phrase": 格子上的说法, "path": 基本信息字段路径}]。
    不合格的格子和建议单独跳过、在返回值里说明原因，其余照常记下（2026-09-29 项目主实测：
    一条 learn 指向列表字段，整批结果都被退回了）。一格合格的都没有时抛 ValueError。
    """
    clean: list[dict] = []
    skipped: list[dict] = []
    for f in fills or []:
        f = f if isinstance(f, dict) else {}
        i, value = f.get("i"), f.get("value")
        if isinstance(i, str) and i.isdigit():
            i = int(i)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(i, int) or isinstance(i, bool) or i < 0:
            skipped.append({"i": f.get("i"), "reason": "格子编号要是非负整数"})
        elif not isinstance(value, str) or not value.strip():
            skipped.append({"i": i, "reason": "值要是非空文字"})
        elif len(value) > MAX_FILL_VALUE:
            skipped.append({"i": i, "reason": f"值太长（最多 {MAX_FILL_VALUE} 字）"})
        else:
            clean.append({"i": i, "value": value.strip()})
    if not clean:
        reasons = "；".join(f"第 {s['i']} 格：{s['reason']}" for s in skipped) or "fills 是空的"
        raise ValueError(f"没有可以交给插件的格子（{reasons}）")
    paths = _profile_paths()
    lessons: list[dict] = []
    learn_skipped: list[str] = []
    for item in learn or []:
        item = item if isinstance(item, dict) else {}
        phrase, path = str(item.get("phrase") or "").strip(), item.get("path")
        if path in paths and phrase:
            lessons.append({"phrase": phrase[:100], "path": path})
        else:
            learn_skipped.append(f"{path}（字段路径不存在或 phrase 为空）")
    entry = {"id": uuid4().hex[:12], "time": _now(), "fills": clean, "learn": lessons}
    entries = (read_form_fills(root) + [entry])[-MAX_FORM_FILLS:]
    path = form_fills_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    return {"fills_id": entry["id"], "count": len(clean), "skipped": skipped,
            "learn": len(lessons), "learn_skipped": learn_skipped}
