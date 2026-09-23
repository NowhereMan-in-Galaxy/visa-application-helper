"""共享区的流程攻略：数据模型 + 校验（specs/002-guide-to-track/spec.md "数据结构 §1"）。

流程攻略是大家共同维护的内容，任何人都能提交，所以校验要严格、报错要说人话：
一份坏攻略只让它自己被标为"无效"并列出原因，不能让整个服务起不来。

命令行用法（贡献者提交前自查，将来也给 CI 用）：
    uv run python -m core.guides
有任何错误时退出码为 1。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from core.material_types import Vocabulary, VocabularyError, load_vocabulary

CATEGORIES = ("签证", "工作", "社保", "银行补贴", "其他")
MAX_QUOTE_CHARS = 60
_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class _Strict(BaseModel):
    # 拼错的字段名直接报错，而不是被悄悄忽略——共同维护的文件最怕"写了但没生效"
    model_config = ConfigDict(extra="forbid")


class Evidence(_Strict):
    source: str
    quote: str


class Condition(_Strict):
    fact: str
    # YAML 里 [是, 否] 这种会被读成字符串，但 [true] 会被读成布尔值，统一收成 str 避免比较时踩坑
    in_: list[str]
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def __init__(self, **data):
        if "in" in data:
            data["in_"] = [str(v) for v in data.pop("in")]
        super().__init__(**data)


class Source(_Strict):
    id: str
    title: str
    url: str | None = None
    as_of: date | None = None


class Fact(_Strict):
    question: str
    options: list[str]
    ask_if: list[Condition] = []


class Requirement(_Strict):
    id: str
    kind: Literal["obtain", "generate", "output"]
    material_type: str | None = None
    raw_name: str | None = None
    optional: bool = False
    applies_if: list[Condition] = []
    freshness_days: int | None = None
    note: str | None = None
    evidence: list[Evidence] = []


class Duration(_Strict):
    typical: int
    max: int


class Phase(_Strict):
    """流程的大阶段（例如"官网填表 → 准备材料 → 线下递交 → 等结果"），显示在页面最上方的进度条里。"""

    id: str
    title: str
    summary: str | None = None
    mode: Literal["online", "offline"] | None = None  # 线上还是线下，没有明确说法时留空
    estimate: str | None = None  # 自由文本，例如"1–2 小时"
    duration_days: Duration | None = None  # 需要等待的天数，用于估算全程要多久
    evidence: list[Evidence] = []


class Step(_Strict):
    id: str
    title: str
    phase: str | None = None
    where: str | None = None
    requirements: list[str] = []
    depends_on: list[str] = []
    applies_if: list[Condition] = []
    estimate: str | None = None
    duration_days: Duration | None = None
    evidence: list[Evidence] = []


class Check(_Strict):
    id: str
    text: str
    involves: list[str] = []
    evidence: list[Evidence] = []


class Claim(_Strict):
    source: str
    quote: str


class Conflict(_Strict):
    id: str
    about: str
    claims: list[Claim]


class Guide(_Strict):
    id: str
    title: str
    category: str
    summary: str | None = None
    maintainers: list[str] = []
    updated: date | None = None
    timeline: str | None = None  # 一句话说明全程一般要多久、要提前多久开始
    sources: list[Source]
    phases: list[Phase] = []
    facts: dict[str, Fact] = {}
    requirements: list[Requirement]
    steps: list[Step]
    checks: list[Check] = []
    conflicts: list[Conflict] = []
    uncertain: list[str] = []


@dataclass
class GuideLoadResult:
    """读一份攻略文件的结果：`guide` 为 None 表示连基本结构都不对；`errors` 非空表示无效。"""

    path: Path
    guide: Guide | None
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.guide is not None and not self.errors


def validate_guide(guide: Guide, vocab: Vocabulary, file_stem: str | None = None) -> list[str]:
    """逐条检查 spec 里的校验规则，返回全部错误（不在第一个错误处停下，方便一次改完）。"""
    errors: list[str] = []

    if not _ID_PATTERN.match(guide.id):
        errors.append(f"id {guide.id!r} 只能包含小写字母、数字和连字符")
    if file_stem is not None and guide.id != file_stem:
        errors.append(f"id {guide.id!r} 必须与文件名 {file_stem!r} 一致")
    if guide.category not in CATEGORIES:
        errors.append(f"category {guide.category!r} 必须是 {' / '.join(CATEGORIES)} 之一")

    def unique(kind: str, ids: list[str]) -> set[str]:
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                errors.append(f"{kind} 的 id 重复：{i}")
            seen.add(i)
        return seen

    source_ids = unique("sources", [s.id for s in guide.sources])
    req_ids = unique("requirements", [r.id for r in guide.requirements])
    step_ids = unique("steps", [s.id for s in guide.steps])
    phase_ids = unique("phases", [p.id for p in guide.phases])
    unique("checks", [c.id for c in guide.checks])
    unique("conflicts", [c.id for c in guide.conflicts])

    for s in guide.sources:
        if s.url and not s.url.startswith(("http://", "https://")):
            errors.append(f"source {s.id}：url 必须以 http:// 或 https:// 开头")

    def check_evidence(owner: str, evidence: list[Evidence], required: bool) -> None:
        if required and not evidence:
            errors.append(f"{owner}：至少需要一条 evidence（原始资料里的原话）")
        for e in evidence:
            if e.source not in source_ids:
                errors.append(f"{owner}：evidence 引用了不存在的 source {e.source}")
            if len(e.quote) > MAX_QUOTE_CHARS:
                errors.append(f"{owner}：evidence 原话 {len(e.quote)} 字，超过 {MAX_QUOTE_CHARS} 字上限")

    def check_conditions(owner: str, conditions: list[Condition], self_fact: str | None = None) -> None:
        for c in conditions:
            fact = guide.facts.get(c.fact)
            if fact is None:
                errors.append(f"{owner}：条件引用了不存在的 fact {c.fact}")
                continue
            if c.fact == self_fact:
                errors.append(f"{owner}：ask_if 不能引用自己")
            for v in c.in_:
                if v not in fact.options:
                    errors.append(f"{owner}：条件值 {v!r} 不在 fact {c.fact} 的选项 {fact.options} 里")

    for name, fact in guide.facts.items():
        if not fact.options:
            errors.append(f"fact {name}：options 不能为空")
        check_conditions(f"fact {name}", fact.ask_if, self_fact=name)

    for r in guide.requirements:
        owner = f"requirement {r.id}"
        if r.material_type is not None and r.material_type not in vocab.types:
            errors.append(f"{owner}：material_type {r.material_type!r} 不在词表里")
        if r.material_type is None and not (r.raw_name or "").strip():
            errors.append(f"{owner}：material_type 为空时 raw_name 必填")
        if r.freshness_days is not None and r.freshness_days <= 0:
            errors.append(f"{owner}：freshness_days 必须是正整数")
        check_conditions(owner, r.applies_if)
        check_evidence(owner, r.evidence, required=True)

    attached: set[str] = set()
    for s in guide.steps:
        owner = f"step {s.id}"
        for rid in s.requirements:
            if rid not in req_ids:
                errors.append(f"{owner}：引用了不存在的 requirement {rid}")
            attached.add(rid)
        for dep in s.depends_on:
            if dep not in step_ids:
                errors.append(f"{owner}：depends_on 引用了不存在的 step {dep}")
        if s.duration_days is not None:
            d = s.duration_days
            if d.typical <= 0 or d.max <= 0 or d.typical > d.max:
                errors.append(f"{owner}：duration_days 需满足 0 < typical <= max")
        check_conditions(owner, s.applies_if)
        check_evidence(owner, s.evidence, required=True)

    for p in guide.phases:
        if p.duration_days is not None and not (0 < p.duration_days.typical <= p.duration_days.max):
            errors.append(f"phase {p.id}：duration_days 需满足 0 < typical <= max")
        check_evidence(f"phase {p.id}", p.evidence, required=False)
    for s in guide.steps:
        if guide.phases and s.phase is None:
            errors.append(f"step {s.id}：攻略定义了 phases，每个步骤都必须写 phase")
        elif s.phase is not None and s.phase not in phase_ids:
            errors.append(f"step {s.id}：phase 引用了不存在的阶段 {s.phase}")
    used_phases = {s.phase for s in guide.steps}
    for p in guide.phases:
        if p.id not in used_phases:
            errors.append(f"phase {p.id}：没有任何步骤属于这个阶段")

    for rid in sorted(req_ids - attached):
        errors.append(f"requirement {rid}：没有挂在任何 step 上（用户照着步骤做会漏掉它）")

    for c in guide.checks:
        for rid in c.involves:
            if rid not in req_ids:
                errors.append(f"check {c.id}：involves 引用了不存在的 requirement {rid}")
        check_evidence(f"check {c.id}", c.evidence, required=False)

    for k in guide.conflicts:
        for claim in k.claims:
            if claim.source not in source_ids:
                errors.append(f"conflict {k.id}：引用了不存在的 source {claim.source}")

    cycle = _find_cycle({s.id: [d for d in s.depends_on if d in step_ids] for s in guide.steps})
    if cycle:
        errors.append(f"步骤依赖成环：{' → '.join(cycle)}")

    return errors


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """深度优先找环；找到时返回环上的节点序列（首尾相同），否则 None。"""
    state: dict[str, int] = {}  # 1 = 正在访问，2 = 访问完毕
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def load_guide(path: Path, vocab: Vocabulary) -> GuideLoadResult:
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return GuideLoadResult(path, None, [f"YAML 格式错误：{e}"])
    try:
        guide = Guide.model_validate(raw)
    except ValidationError as e:
        messages = [
            f"{'.'.join(str(p) for p in err['loc'])}：{err['msg']}" for err in e.errors()
        ]
        return GuideLoadResult(path, None, messages)
    return GuideLoadResult(path, guide, validate_guide(guide, vocab, file_stem=path.stem))


def load_all_guides(guides_dir: Path, vocab: Vocabulary) -> list[GuideLoadResult]:
    if not guides_dir.is_dir():
        return []
    return [load_guide(p, vocab) for p in sorted(guides_dir.glob("*.yaml"))]


def main() -> int:
    from config import COMMUNITY_DIR

    try:
        vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    except VocabularyError as e:
        print(f"✗ community/material_types.yaml：{e}")
        return 1
    print(f"✓ community/material_types.yaml：{len(vocab.types)} 种材料类型")

    results = load_all_guides(COMMUNITY_DIR / "guides", vocab)
    failed = 0
    for r in results:
        rel = r.path.relative_to(COMMUNITY_DIR.parent)
        if r.valid:
            g = r.guide
            unresolved = [
                q.id for q in g.requirements
                if (q.material_type or vocab.lookup(q.raw_name)) is None
            ]
            note = f"，{len(unresolved)} 条材料叫法词表认不出：{', '.join(unresolved)}" if unresolved else ""
            print(f"✓ {rel}：{len(g.requirements)} 条需求、{len(g.steps)} 个步骤{note}")
        else:
            failed += 1
            print(f"✗ {rel}：")
            for msg in r.errors:
                print(f"    - {msg}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
