"""办事官网的自动化条款（community/site_policies.yaml，specs/006-browser-extension）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import yaml


class SitePoliciesError(ValueError):
    pass


@dataclass(frozen=True)
class SitePolicy:
    host: str
    name: str
    automation: str
    clause: str | None
    consequence: str | None
    url: str | None
    checked: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_site_policies(path: Path) -> list[SitePolicy]:
    """读并检查；有问题抛 SitePoliciesError，信息里列出全部错误。"""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise SitePoliciesError(str(e)) from e
    errors: list[str] = []
    out: list[SitePolicy] = []
    seen: set[str] = set()
    for n, item in enumerate(data.get("sites") or [], 1):
        item = item or {}
        host = str(item.get("host") or "").strip().lower()
        where = host or f"第 {n} 条"
        missing = [k for k in ("host", "name", "automation", "checked") if not item.get(k)]
        if missing:
            errors.append(f"{where}：缺少 {', '.join(missing)}")
            continue
        if item["automation"] not in ("forbidden", "allowed"):
            errors.append(f"{where}：automation 只能是 forbidden 或 allowed")
            continue
        if item["automation"] == "forbidden" and not item.get("clause"):
            errors.append(f"{where}：forbidden 的网站要写 clause（条款原话）")
            continue
        if host in seen:
            errors.append(f"{where}：host 重复")
            continue
        seen.add(host)
        checked = item["checked"]
        out.append(SitePolicy(
            host=host, name=str(item["name"]), automation=item["automation"],
            clause=item.get("clause"), consequence=item.get("consequence"), url=item.get("url"),
            checked=checked.isoformat() if isinstance(checked, date) else str(checked),
        ))
    if errors:
        raise SitePoliciesError("；".join(errors))
    return out


def policy_for(host: str, policies: list[SitePolicy]) -> dict:
    """按域名找条款记录；子域名也算。找不到时 automation 为 unknown。"""
    host = (host or "").strip().lower().split(":")[0]
    for p in policies:
        if host == p.host or host.endswith("." + p.host):
            return p.to_dict()
    return {"host": host, "name": None, "automation": "unknown", "clause": None,
            "consequence": None, "url": None, "checked": None}


def default_site_policies() -> list[SitePolicy]:
    from config import COMMUNITY_DIR
    return load_site_policies(COMMUNITY_DIR / "site_policies.yaml")
