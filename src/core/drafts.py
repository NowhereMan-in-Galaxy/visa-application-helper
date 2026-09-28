"""攻略草稿（spec 004"数据与存储"）：Agent 整理出来、还没被用户保存进攻略库的攻略。

- 草稿放在 `<材料根目录>/drafts/<攻略类型>/<id>.yaml`（材料根目录被 git 忽略：没经用户检视的内容不能进仓库）。
- 旁边的 `<id>.meta.json` 存 Agent 给的词表别名建议。
- 发布由这里的确定性代码完成（不是 Agent）：重新校验 → 写进 community/ → 删除草稿。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.guide_types import get_guide_type
from core.guides import load_guide
from core.material_types import Vocabulary

DRAFT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
MAX_DRAFT_BYTES = 200_000


class DraftError(Exception):
    """草稿操作失败；status 是给 HTTP 接口用的状态码。"""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _type_or_error(type_id: str):
    t = get_guide_type(type_id)
    if t is None:
        raise DraftError(f"没有这种攻略类型：{type_id}", 404)
    if not t.available or t.community_subdir is None:
        raise DraftError(f"「{t.name}」还不能新建", 422)
    return t


def _check_id(draft_id: str) -> None:
    if not DRAFT_ID.match(draft_id or ""):
        raise DraftError(f"草稿 id {draft_id!r} 只能用小写字母、数字和连字符，最长 80 个字符")


def drafts_dir(root: Path, type_id: str) -> Path:
    return root / "drafts" / type_id


def _paths(root: Path, type_id: str, draft_id: str) -> tuple[Path, Path]:
    _type_or_error(type_id)
    _check_id(draft_id)
    d = drafts_dir(root, type_id)
    return d / f"{draft_id}.yaml", d / f"{draft_id}.meta.json"


def _read_meta(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def check_draft(root: Path, type_id: str, draft_id: str, vocab: Vocabulary,
                form_ids: set[str] | None = None) -> dict:
    """校验一份草稿，返回页面和 Agent 都能用的结果。"""
    path, meta_path = _paths(root, type_id, draft_id)
    if not path.is_file():
        raise DraftError(f"没有找到草稿：{draft_id}", 404)
    result = load_guide(path, vocab, form_ids)
    g = result.guide
    unresolved = []
    if g is not None:
        unresolved = [
            {"requirement": q.id, "raw_name": q.raw_name}
            for q in g.requirements if (q.material_type or vocab.lookup(q.raw_name)) is None
        ]
    meta = _read_meta(meta_path)
    return {
        "type": type_id,
        "id": draft_id,
        "title": g.title if g else None,
        "valid": result.valid,
        "errors": result.errors,
        "unresolved": unresolved,
        "alias_suggestions": meta.get("alias_suggestions", []),
        "updated_at": meta.get("updated_at"),
        "requirement_count": len(g.requirements) if g else 0,
        "step_count": len(g.steps) if g else 0,
        "uncertain": list(g.uncertain) if g else [],
        "conflict_count": len(g.conflicts) if g else 0,
    }


def save_draft(root: Path, type_id: str, draft_id: str, text: str, vocab: Vocabulary,
               alias_suggestions: list[dict] | None = None, form_ids: set[str] | None = None) -> dict:
    """写入（或覆盖）一份草稿并立即校验。只写草稿区，绝不碰 community/。"""
    path, meta_path = _paths(root, type_id, draft_id)
    if len(text.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise DraftError("草稿太大（上限 200 KB）")
    clean = []
    for s in alias_suggestions or []:
        raw, key = str((s or {}).get("raw_name", "")).strip(), str((s or {}).get("key", "")).strip()
        if raw and key in vocab.types:
            clean.append({"raw_name": raw, "key": key, "key_name": vocab.types[key].name})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    meta_path.write_text(json.dumps({
        "alias_suggestions": clean,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return check_draft(root, type_id, draft_id, vocab, form_ids)


def read_draft_text(root: Path, type_id: str, draft_id: str) -> str:
    path, _ = _paths(root, type_id, draft_id)
    if not path.is_file():
        raise DraftError(f"没有找到草稿：{draft_id}", 404)
    return path.read_text(encoding="utf-8")


def list_drafts(root: Path, vocab: Vocabulary, form_ids: set[str] | None = None) -> list[dict]:
    out = []
    base = root / "drafts"
    if not base.is_dir():
        return out
    for type_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        t = get_guide_type(type_dir.name)
        if t is None or not t.available:
            continue
        for p in sorted(type_dir.glob("*.yaml")):
            if DRAFT_ID.match(p.stem):
                out.append(check_draft(root, t.id, p.stem, vocab, form_ids))
    return out


def delete_draft(root: Path, type_id: str, draft_id: str) -> None:
    path, meta_path = _paths(root, type_id, draft_id)
    if not path.is_file():
        raise DraftError(f"没有找到草稿：{draft_id}", 404)
    path.unlink()
    meta_path.unlink(missing_ok=True)


def publish_draft(root: Path, type_id: str, draft_id: str, community_dir: Path, vocab: Vocabulary,
                  form_ids: set[str] | None = None) -> Path:
    """校验通过才发布；同名攻略已存在时拒绝（第一版不支持覆盖）。"""
    t = _type_or_error(type_id)
    check = check_draft(root, type_id, draft_id, vocab, form_ids)
    if not check["valid"]:
        raise DraftError("草稿没有通过校验，不能保存：" + "；".join(check["errors"]))
    target = community_dir / t.community_subdir / f"{draft_id}.yaml"
    if target.exists():
        raise DraftError(f"攻略库里已经有 {draft_id} 了，换一个 id 再保存", 409)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(read_draft_text(root, type_id, draft_id), encoding="utf-8")
    delete_draft(root, type_id, draft_id)
    return target
