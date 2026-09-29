"""共享区的流程攻略：数据模型 + 校验（specs/002-guide-to-track/spec.md "数据结构 §1"）。

流程攻略是大家共同维护的内容，任何人都能提交，所以校验要严格、报错要说人话：
一份坏攻略只让它自己被标为"无效"并列出原因，不能让整个服务起不来。

命令行用法（贡献者提交前自查，将来也给 CI 用）：
    uv run python -m core.guides
有任何错误时退出码为 1。
"""

from __future__ import annotations

import re
import string
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from core.material_types import Vocabulary, VocabularyError, load_vocabulary

CATEGORIES = ("签证", "工作", "社保", "补贴", "银行补贴", "其他")
# 导出文件名模板里允许的占位符：{seq} 序号（可写 {seq:02d}）、{name} 材料名、{part} 组合材料的部分名
EXPORT_PLACEHOLDERS = {"seq", "name", "part"}
DEFAULT_EXPORT_PATTERN = "{seq:02d}-{name}"
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]')
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
    # choice = 从 options 里选一个；date = 填一个日期（毕业日期、首次参保日期……），给步骤的时间窗当基准
    type: Literal["choice", "date"] = "choice"
    options: list[str] = []
    ask_if: list[Condition] = []


class DateRef(_Strict):
    """时间窗的一端（spec §3c）：某个日期类问题的答案，或某个步骤勾完的日期，再往后（或往前）挪一段。"""

    fact: str | None = None
    step: str | None = None
    months: int = 0
    days: int = 0
    end_of: Literal["month", "year"] | None = None  # 挪完之后取那个月 / 那年的最后一天


class Window(_Strict):
    """步骤的可办时间窗：opens 之前还不能办，closes 之后就错过了。两端至少写一个。"""

    opens: DateRef | None = None
    closes: DateRef | None = None


class Requirement(_Strict):
    id: str
    kind: Literal["obtain", "generate", "output"]
    material_type: str | None = None
    raw_name: str | None = None
    export_name: str | None = None  # 导出时用的名字（例如按官方清单编号"01-护照复印件"）；不写就用标准材料名
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


class Link(_Strict):
    """步骤上挂的链接：官网、填表指南（本仓库 community/forms/ 里另写的一份）或参考资料。"""

    title: str
    kind: Literal["official", "form_guide", "info"] = "info"
    url: str | None = None  # 外部链接，仅 http/https
    form: str | None = None  # 填表指南 id，对应 community/forms/<id>.yaml；和 url 二选一
    applies_if: list[Condition] = []  # 例如只有"申请国 = 法国"时才显示法国官网
    evidence: list[Evidence] = []
    # 最近一次有人（或 Agent 带浏览器）实际打开、确认是官方站点且内容对得上的日期；没核实过就留空
    verified: date | None = None


class Step(_Strict):
    id: str
    title: str
    phase: str | None = None
    links: list[Link] = []
    where: str | None = None
    requirements: list[str] = []
    depends_on: list[str] = []
    applies_if: list[Condition] = []
    estimate: str | None = None
    duration_days: Duration | None = None
    window: Window | None = None
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
    # 攻略库里用来筛选和搜索的标签（国家/地区、城市、人群、办理方式……），见 spec "数据结构 §1"
    tags: list[str] = []
    maintainers: list[str] = []
    updated: date | None = None
    timeline: str | None = None  # 一句话说明全程一般要多久、要提前多久开始
    # 导出文件名模板，占位符见 EXPORT_PLACEHOLDERS；不写时用 DEFAULT_EXPORT_PATTERN
    export_pattern: str | None = None
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


def validate_export_pattern(pattern: str) -> str | None:
    """检查导出文件名模板；合格返回 None，否则返回中文错误原因。"""
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(pattern) if f is not None]
    except ValueError as e:
        return f"export_pattern 格式错误：{e}"
    unknown = [f for f in fields if f not in EXPORT_PLACEHOLDERS]
    if unknown:
        return f"export_pattern 只能用占位符 {{seq}} {{name}} {{part}}，出现了：{', '.join(unknown)}"
    if "name" not in fields and "seq" not in fields:
        return "export_pattern 至少要包含 {seq} 或 {name}，否则导出的文件会重名"
    try:
        sample = pattern.format(seq=1, name="材料", part="部分")
    except (ValueError, KeyError, IndexError) as e:
        return f"export_pattern 无法套用：{e}"
    if _BAD_FILENAME_CHARS.search(sample):
        return "export_pattern 里不能有 / \\ : * ? \" < > | 等文件名不允许的字符"
    return None


def validate_guide(
    guide: Guide, vocab: Vocabulary, file_stem: str | None = None, form_ids: set[str] | None = None
) -> list[str]:
    """逐条检查 spec 里的校验规则，返回全部错误（不在第一个错误处停下，方便一次改完）。

    `form_ids` 为 None 时不检查链接引用的填表指南是否存在（例如单元测试里没有 forms 目录）。
    """
    errors: list[str] = []

    if not _ID_PATTERN.match(guide.id):
        errors.append(f"id {guide.id!r} 只能包含小写字母、数字和连字符")
    if file_stem is not None and guide.id != file_stem:
        errors.append(f"id {guide.id!r} 必须与文件名 {file_stem!r} 一致")
    if guide.category not in CATEGORIES:
        errors.append(f"category {guide.category!r} 必须是 {' / '.join(CATEGORIES)} 之一")
    for t in guide.tags:
        if not t.strip() or len(t) > 12 or t != t.strip():
            errors.append(f"标签 {t!r} 要是 1–12 个字、前后不带空格")
    if len(set(guide.tags)) != len(guide.tags):
        errors.append("tags 里有重复的标签")
    if guide.category in guide.tags:
        errors.append(f"标签不用重复写分类 {guide.category!r}")

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
            if fact.type == "date":
                errors.append(f"{owner}：条件不能引用日期类问题 {c.fact}（日期没有选项可比）")
                continue
            for v in c.in_:
                if v not in fact.options:
                    errors.append(f"{owner}：条件值 {v!r} 不在 fact {c.fact} 的选项 {fact.options} 里")

    for name, fact in guide.facts.items():
        if fact.type == "choice" and not fact.options:
            errors.append(f"fact {name}：options 不能为空")
        if fact.type == "date" and fact.options:
            errors.append(f"fact {name}：日期类问题不写 options")
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
        if s.window is not None:
            if s.window.opens is None and s.window.closes is None:
                errors.append(f"{owner}：window 的 opens 和 closes 至少写一个")
            for end, ref in (("opens", s.window.opens), ("closes", s.window.closes)):
                if ref is None:
                    continue
                where = f"{owner} 的 window.{end}"
                if (ref.fact is None) == (ref.step is None):
                    errors.append(f"{where}：fact 和 step 必须二选一")
                elif ref.fact is not None:
                    f = guide.facts.get(ref.fact)
                    if f is None:
                        errors.append(f"{where}：引用了不存在的 fact {ref.fact}")
                    elif f.type != "date":
                        errors.append(f"{where}：fact {ref.fact} 不是日期类问题（type: date）")
                elif ref.step not in s.depends_on:
                    errors.append(f"{where}：引用的步骤 {ref.step} 必须写在 depends_on 里")

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

    if guide.export_pattern is not None:
        problem = validate_export_pattern(guide.export_pattern)
        if problem:
            errors.append(problem)
    for r in guide.requirements:
        if r.export_name is not None and (not r.export_name.strip() or _BAD_FILENAME_CHARS.search(r.export_name)):
            errors.append(f"requirement {r.id}：export_name 不能为空，也不能含文件名不允许的字符")

    for s in guide.steps:
        for i, link in enumerate(s.links):
            owner = f"step {s.id} 的第 {i + 1} 个链接"
            if (link.url is None) == (link.form is None):
                errors.append(f"{owner}：url 和 form 必须二选一")
            if link.url is not None and not link.url.startswith(("http://", "https://")):
                errors.append(f"{owner}：url 必须以 http:// 或 https:// 开头")
            if link.form is not None and form_ids is not None and link.form not in form_ids:
                errors.append(f"{owner}：填表指南 {link.form} 不存在（community/forms/{link.form}.yaml）")
            if link.kind == "form_guide" and link.form is None:
                errors.append(f"{owner}：kind 为 form_guide 时必须用 form 指向 community/forms/ 里的指南")
            check_conditions(owner, link.applies_if)
            check_evidence(owner, link.evidence, required=False)

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


def load_guide(path: Path, vocab: Vocabulary, form_ids: set[str] | None = None) -> GuideLoadResult:
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
    return GuideLoadResult(path, guide, validate_guide(guide, vocab, file_stem=path.stem, form_ids=form_ids))


def load_all_guides(guides_dir: Path, vocab: Vocabulary) -> list[GuideLoadResult]:
    """读一个目录下的全部攻略。旁边有 forms/ 目录时（community/forms），顺带检查链接引用的填表指南是否存在。"""
    if not guides_dir.is_dir():
        return []
    forms_dir = guides_dir.parent / "forms"
    form_ids = {p.stem for p in forms_dir.glob("*.yaml")} if forms_dir.is_dir() else None
    return [load_guide(p, vocab, form_ids) for p in sorted(guides_dir.glob("*.yaml"))]


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

    from core.forms import load_all_forms  # 放在这里导入：forms 模块依赖本模块，避免循环导入

    for f in load_all_forms(COMMUNITY_DIR / "forms"):
        rel = f.path.relative_to(COMMUNITY_DIR.parent)
        if f.valid:
            print(f"✓ {rel}：{len(f.form.sections)} 节（{'流程级' if f.form.level == 'procedure' else '字段级'}）")
        else:
            failed += 1
            print(f"✗ {rel}：")
            for msg in f.errors:
                print(f"    - {msg}")

    from form_engine.match import FormFieldsError, load_dictionary

    try:
        d = load_dictionary(COMMUNITY_DIR / "form_fields.yaml")
        print(f"✓ community/form_fields.yaml：{len(d.entries)} 个字段")
    except FormFieldsError as e:
        failed += 1
        print(f"✗ community/form_fields.yaml：{e}")

    from form_engine.sites import SitePoliciesError, load_site_policies

    try:
        sites = load_site_policies(COMMUNITY_DIR / "site_policies.yaml")
        forbidden = sum(1 for s in sites if s.automation == "forbidden")
        print(f"✓ community/site_policies.yaml：{len(sites)} 个网站，{forbidden} 个禁止自动化")
    except SitePoliciesError as e:
        failed += 1
        print(f"✗ community/site_policies.yaml：{e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
