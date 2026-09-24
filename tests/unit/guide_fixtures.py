"""测试用的最小攻略和词表（全部虚构）。每个测试在这份"合格"的基础上改一处，看校验/状态是否符合预期。"""

import copy

from core.guides import Guide
from core.material_types import build_vocabulary

VOCAB = build_vocabulary({
    "normalize": ["原件", "复印件"],
    "types": [
        {"key": "bank_statement", "name": "银行流水", "category": "financial_snapshot", "aliases": []},
        {"key": "employment_letter", "name": "在职证明", "category": "employment_doc", "aliases": []},
        {"key": "passport_bio_page", "name": "护照个人信息页", "category": "passport_scan", "aliases": []},
        {"key": "passport_visa_page", "name": "护照签证页", "category": "passport_scan", "aliases": []},
        {
            "key": "passport_full_copy", "name": "护照全部页", "category": "passport_scan", "aliases": [],
            "parts": ["passport_bio_page", "passport_visa_page"],
        },
        {"key": "sponsor_documents", "name": "出资人材料", "category": None, "aliases": []},
    ],
})

_BASE = {
    "id": "demo-guide",
    "title": "虚构的示例签证",
    "category": "签证",
    "sources": [{"id": "g1", "title": "示例来源", "url": "https://example.com/a", "as_of": "2026-01-01"}],
    "facts": {
        "identity": {"question": "身份？", "options": ["在职", "学生"]},
        "sponsored": {"question": "有人出资？", "options": ["是", "否"]},
        "same_hukou": {
            "question": "同户口本？", "options": ["是", "否"],
            "ask_if": [{"fact": "sponsored", "in": ["是"]}],
        },
    },
    "requirements": [
        {"id": "r-bank", "kind": "obtain", "material_type": "bank_statement", "freshness_days": 30,
         "evidence": [{"source": "g1", "quote": "流水"}]},
        {"id": "r-job", "kind": "obtain", "material_type": "employment_letter",
         "applies_if": [{"fact": "identity", "in": ["在职"]}], "evidence": [{"source": "g1", "quote": "在职证明"}]},
        {"id": "r-passport", "kind": "obtain", "material_type": "passport_full_copy",
         "evidence": [{"source": "g1", "quote": "护照"}]},
        {"id": "r-kinship", "kind": "obtain", "raw_name": "亲属关系公证",
         "applies_if": [{"fact": "sponsored", "in": ["是"]}, {"fact": "same_hukou", "in": ["否"]}],
         "evidence": [{"source": "g1", "quote": "公证"}]},
        {"id": "r-extra", "kind": "obtain", "raw_name": "银行流水原件", "optional": True,
         "evidence": [{"source": "g1", "quote": "加分"}]},
    ],
    "steps": [
        {"id": "s-bank", "title": "打流水", "requirements": ["r-bank", "r-extra"], "evidence": [{"source": "g1", "quote": "去银行"}]},
        {"id": "s-job", "title": "开在职证明", "requirements": ["r-job"],
         "applies_if": [{"fact": "identity", "in": ["在职"]}], "evidence": [{"source": "g1", "quote": "找公司"}]},
        {"id": "s-docs", "title": "复印", "requirements": ["r-passport", "r-kinship"], "evidence": [{"source": "g1", "quote": "复印"}]},
        {"id": "s-submit", "title": "递交", "depends_on": ["s-bank", "s-job", "s-docs"],
         "evidence": [{"source": "g1", "quote": "递交"}], "duration_days": {"typical": 10, "max": 20}},
    ],
    "checks": [{"id": "c-1", "text": "姓名一致", "involves": ["r-bank", "r-passport"]}],
}


def guide_dict() -> dict:
    return copy.deepcopy(_BASE)


def make_guide(**overrides) -> Guide:
    data = guide_dict()
    data.update(overrides)
    return Guide.model_validate(data)
