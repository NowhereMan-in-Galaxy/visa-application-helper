"""填表指南（specs/002-guide-to-track/spec.md "官网填表指引"）：共享区 community/forms/<id>.yaml。

和流程攻略一样是共享内容，只记录"官网怎么填、按什么顺序"，**不含任何人的答案**。
目前是"流程级"（level: procedure）：按页面/环节列出要做什么、注意什么；以后由 Agent 带着浏览器
实际走一遍官网后，再补"字段级"（level: field）的逐项说明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from core.guides import _ID_PATTERN, MAX_QUOTE_CHARS, Evidence, Source, _Strict


class Site(_Strict):
    name: str
    url: str


class FormSection(_Strict):
    title: str
    items: list[str]  # 按顺序要做的事
    tips: list[str] = []  # 容易踩的坑
    evidence: list[Evidence] = []


class FormGuide(_Strict):
    id: str
    title: str
    level: Literal["procedure", "field"] = "procedure"
    site: Site
    summary: str | None = None
    updated: date | None = None
    sources: list[Source]
    sections: list[FormSection]
    uncertain: list[str] = []


@dataclass
class FormLoadResult:
    path: Path
    form: FormGuide | None
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.form is not None and not self.errors


def validate_form(form: FormGuide, file_stem: str | None = None) -> list[str]:
    errors: list[str] = []
    if not _ID_PATTERN.match(form.id):
        errors.append(f"id {form.id!r} 只能包含小写字母、数字和连字符")
    if file_stem is not None and form.id != file_stem:
        errors.append(f"id {form.id!r} 必须与文件名 {file_stem!r} 一致")
    urls = [("site.url", form.site.url)] + [(f"source {s.id}", s.url) for s in form.sources if s.url]
    for owner, url in urls:
        if not url.startswith(("http://", "https://")):
            errors.append(f"{owner}：url 必须以 http:// 或 https:// 开头")
    source_ids = [s.id for s in form.sources]
    if len(source_ids) != len(set(source_ids)):
        errors.append("sources 的 id 重复")
    if not form.sections:
        errors.append("至少需要一个 section")
    for i, sec in enumerate(form.sections):
        owner = f"第 {i + 1} 节「{sec.title}」"
        if not sec.items:
            errors.append(f"{owner}：items 不能为空")
        for e in sec.evidence:
            if e.source not in source_ids:
                errors.append(f"{owner}：evidence 引用了不存在的 source {e.source}")
            if len(e.quote) > MAX_QUOTE_CHARS:
                errors.append(f"{owner}：evidence 原话超过 {MAX_QUOTE_CHARS} 字上限")
    return errors


def load_form(path: Path) -> FormLoadResult:
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return FormLoadResult(path, None, [f"YAML 格式错误：{e}"])
    try:
        form = FormGuide.model_validate(raw)
    except ValidationError as e:
        return FormLoadResult(path, None, [f"{'.'.join(str(p) for p in err['loc'])}：{err['msg']}" for err in e.errors()])
    return FormLoadResult(path, form, validate_form(form, file_stem=path.stem))


def load_all_forms(forms_dir: Path) -> list[FormLoadResult]:
    if not forms_dir.is_dir():
        return []
    return [load_form(p) for p in sorted(forms_dir.glob("*.yaml"))]
