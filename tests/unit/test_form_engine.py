"""spec 005：通用填表引擎（识别 + 填写计划）。

扫描结果 tests/fixtures/forms/generic-form.scan.json 是在项目主的 Chrome 里（Claude in Chrome）对
generic-form.html 运行 scan.js、再按 900 字分段读回拼起来的原文。基本信息全部是虚构的示例值。
"""

import html
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from config import COMMUNITY_DIR
from core.models import PersonalProfile
from form_engine import match

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "forms"
SCAN_TEXT = (FIXTURES / "generic-form.scan.json").read_text(encoding="utf-8").strip()
SCAN = {"fields": match.expand_scan(SCAN_TEXT)}
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PROFILE = PersonalProfile.model_validate({
    "identity": {
        "surname": "EXAMPLE", "given_names": "SAMPLE ONE", "native_full_name": "示例人",
        "sex": "female", "date_of_birth": "1990-06-15", "birth_city": "Sampletown",
        "nationality": "中国", "national_id_number": "000000199006150000",
    },
    "passport": {"passport_number": "E00000000", "issue_date": "2020-03-05", "expiry_date": "2030-03-04"},
    "contact": {
        "home_address": {"street": "1 Example Road", "city": "Testville", "postal_code": "100000"},
        "primary_phone": "13800000000", "email": "sample@example.com",
    },
    "family": {
        "marital_status": "single",
        "father": {"surname": "EXAMPLE", "given_names": "FATHERNAME"},
        "mother": {"surname": "MOTHERNAME"},
    },
})
SECRET_VALUES = ["EXAMPLE", "SAMPLE ONE", "示例人", "1990", "Sampletown", "000000199006150000", "E00000000",
                 "2020", "2030", "1 Example Road", "Testville", "100000", "13800000000", "sample@example.com",
                 "FATHERNAME", "MOTHERNAME"]

# 格子 → 应该认成的字段（验收标准 1）
EXPECTED = {
    0: "identity.surname", 1: "identity.given_names", 2: "identity.date_of_birth", 3: "identity.sex",
    4: "identity.nationality", 5: "family.marital_status", 6: "passport.passport_number",
    7: "passport.issue_date", 8: "passport.issue_date", 9: "passport.issue_date", 10: "passport.expiry_date",
    11: "contact.home_address.street", 12: "contact.home_address.city", 13: "contact.home_address.postal_code",
    15: "contact.primary_phone", 16: "contact.email", 17: "identity.birth_city",
    18: "family.father.surname", 19: "family.father.given_names", 20: "family.mother.surname",
    21: "identity.native_full_name", 22: "identity.national_id_number", 24: "contact.secondary_phone",
}
SENSITIVE = ["identity.date_of_birth", "passport.passport_number", "identity.national_id_number"]


@pytest.fixture(scope="module")
def d():
    return match.default_dictionary()


def by_i(items):
    return {x["i"]: x["path"] for x in items}


def test_dictionary_is_valid(d):
    leaves = match.profile_leaves()
    assert len(d.entries) >= 40
    for e in d.entries:
        assert e.path in leaves and e.match and all(e.match)
    assert d.values["yes"] and d.values["no"]


def test_bad_dictionary_rejected(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text("fields:\n  identity.no_such: {match: [[x]]}\n  identity.other_names: {match: [[x]]}\n"
                 "  identity.surname: {match: []}\n", encoding="utf-8")
    with pytest.raises(match.FormFieldsError) as e:
        match.load_dictionary(p)
    msg = str(e.value)
    assert "identity.no_such" in msg and "identity.other_names" in msg and "identity.surname" in msg


def test_fixture_plan_matches_expected(d):
    r = match.plan(SCAN["fields"], PROFILE, d, allow_sensitive=SENSITIVE)
    got = {**by_i(r["fill"]), **by_i(r["missing"])}
    assert got == EXPECTED
    assert r["already_filled"] == [14]
    assert [u["i"] for u in r["unmatched"]] == [23]
    assert by_i(r["missing"]) == {24: "contact.secondary_phone"}
    assert r["sensitive"] == [] and r["needs_format"] == []


def test_sensitive_skipped_by_default(d):
    r = match.plan(SCAN["fields"], PROFILE, d)
    assert sorted(set(by_i(r["sensitive"]).values())) == sorted(SENSITIVE)
    assert not set(by_i(r["fill"]).values()) & set(SENSITIVE)
    assert "E00000000" not in r["script"] and "000000199006150000" not in r["script"]
    # 只放行护照号：生日和身份证号仍然不填
    r2 = match.plan(SCAN["fields"], PROFILE, d, allow_sensitive=["passport.passport_number"])
    assert 6 in by_i(r2["fill"]) and "E00000000" in r2["script"]
    assert {2, 22} <= set(by_i(r2["sensitive"]))


def test_report_contains_no_values(d):
    r = match.plan(SCAN["fields"], PROFILE, d, allow_sensitive=SENSITIVE)
    report = json.dumps({k: v for k, v in r.items() if k != "script"}, ensure_ascii=False)
    for v in SECRET_VALUES:
        assert v not in report, v


def test_script_carries_plan_once(d):
    """填写计划只出现在脚本末尾一次（注释里不能再复制一份个人信息）。"""
    script = match.plan(SCAN["fields"], PROFILE, d, allow_sensitive=SENSITIVE)["script"]
    assert script.count("SAMPLE ONE") == 1
    assert "__PLAN__" not in script


def ops_of(script):
    return {op["i"]: op for op in json.loads(re.search(r"\}\)\((\[.*\])\)\s*$", script, re.S).group(1))}


def test_values_and_formats(d):
    ops = ops_of(match.plan(SCAN["fields"], PROFILE, d, allow_sensitive=SENSITIVE)["script"])
    assert ops[2] == {"i": 2, "k": "text", "v": "15/06/1990"}           # 占位符 DD/MM/YYYY
    assert ops[7]["c"][:2] == ["05", "5"]                                 # 拆开的日期：日
    assert "mar" in ops[8]["c"] and "3" in ops[8]["c"]                    # 月
    assert ops[9] == {"i": 9, "k": "text", "v": "2020"}                   # 年
    assert ops[10]["v"] == "2030-03-04"                                    # type=date
    assert "female" in ops[3]["c"] and "女" in ops[3]["c"]
    assert "China" in ops[4]["c"] and "chin" in ops[4]["c"]               # 基本信息写"中国"也能对上
    assert "single" in ops[5]["c"]


def test_scan_text_split_and_joined():
    """浏览器工具一次只回传约 1000 字：按 900 字切开再拼回，结果不变；少读一段要报错。"""
    parts = [SCAN_TEXT[k:k + 900] for k in range(0, len(SCAN_TEXT), 900)]
    assert len(parts) == 2 and max(len(p) for p in parts) < 1000
    assert match.expand_scan("".join(parts)) == SCAN["fields"]
    f3 = SCAN["fields"][3]
    assert f3["kind"] == "radio" and f3["section"] == "Sex" and f3["filled"] is False
    assert SCAN["fields"][14]["filled"] is True
    with pytest.raises(match.ScanError):
        match.expand_scan(parts[0])
    with pytest.raises(match.ScanError):
        match.expand_scan('{"fields": []}')


def test_confusable_fields(d):
    def one(**f):
        return match.match_field({"kind": "text", **f}, d)
    assert one(label="Surname") == "identity.surname"
    assert one(label="Father's Surname") == "family.father.surname"
    assert one(label="Spouse's Surname") == "family.spouse.surname"
    assert one(label="Other Surnames Used") is None
    assert one(label="City", section="Home Address") == "contact.home_address.city"
    assert one(label="City", section="Place of Birth") == "identity.birth_city"
    assert one(label="Email Address") == "contact.email"
    assert one(label="Address Line 2") is None
    assert one(label="Passport Book Number") == "passport.passport_book_number"
    assert one(label="姓名") == "identity.native_full_name"
    assert one(label="名") == "identity.given_names"
    assert one(label="单位名称") == "employment.current.name"
    assert one(name="ctl00_SiteContentPlaceHolder_FormView1_tbxAPP_SURNAME") == "identity.surname"
    assert one(label="Anything", autocomplete="given-name") == "identity.given_names"


def test_date_parts():
    assert match.date_part({"name": "ddlDOBDay"}) == "day"
    assert match.date_part({"name": "ddlDOBMonth"}) == "month"
    assert match.date_part({"label": "出生日期（年）"}) == "year"
    assert match.date_part({"label": "出生日期"}) is None
    assert match.date_part({"label": "Date of birth", "placeholder": "DD/MM/YYYY"}) is None
    assert match.date_part({"autocomplete": "bday-month"}) == "month"
    assert match.format_date(date(1990, 6, 5), "dd-mmm-yyyy") == "05-JUN-1990"


def test_unknown_date_format_needs_agent(d):
    r = match.plan([{"i": 0, "kind": "text", "label": "Date of Birth"}], PROFILE, d,
                   allow_sensitive=["identity.date_of_birth"])
    assert by_i(r["needs_format"]) == {0: "identity.date_of_birth"}


def test_mcp_tools_registered():
    from agent_tools import mcp_server, tools
    assert "(() =>" in tools.get_form_scan_script()["script"]
    r = tools.plan_form_fill(SCAN_TEXT, materials_root=None, profile=PROFILE)
    assert set(r) >= {"fill", "sensitive", "missing", "needs_format", "already_filled", "unmatched", "script"}
    assert hasattr(mcp_server, "plan_form_fill") and hasattr(mcp_server, "get_form_scan_script")


def test_community_check_lists_dictionary(capsys):
    from core import guides
    assert guides.main() == 0
    assert "✓ community/form_fields.yaml：" in capsys.readouterr().out
    assert (COMMUNITY_DIR / "form_fields.yaml").is_file()


# ---- 验收 3：真实浏览器里扫描 + 填写（本机有 Chrome 时才跑） ----

@pytest.mark.skipif(not Path(CHROME).exists() and not shutil.which("google-chrome"), reason="没有 Chrome")
def test_fill_in_headless_chrome(d, tmp_path):
    r = match.plan(SCAN["fields"], PROFILE, d, allow_sensitive=SENSITIVE)
    scan = match.scan_script().strip()
    fill = r["script"].strip()
    js = (f"var __s = {scan}; var __f = {fill};"
          'document.getElementById("pa-out").textContent = JSON.stringify({fill: JSON.parse(__f),'
          ' values: Object.fromEntries([...document.querySelectorAll("input,select,textarea")]'
          '.filter(e => e.type !== "hidden").map(e => [e.name || e.id, e.type === "radio" ? '
          '(e.checked ? e.value : null) : e.value]).filter(([k, v]) => v !== null)),'
          ' marked: document.querySelectorAll("[style*=dashed]").length});')
    page = tmp_path / "page.html"
    src = (FIXTURES / "generic-form.html").read_text(encoding="utf-8")
    page.write_text(src.replace("</body>", f'<pre id="pa-out"></pre><script>{js}</script></body>'), encoding="utf-8")
    exe = CHROME if Path(CHROME).exists() else shutil.which("google-chrome")
    dom = subprocess.run([exe, "--headless=new", "--disable-gpu", "--dump-dom", page.as_uri()],
                         capture_output=True, text=True, timeout=60).stdout
    out = json.loads(html.unescape(re.search(r'<pre id="pa-out">(.*?)</pre>', dom, re.S).group(1)))
    v = out["values"]
    assert out["fill"] == {"filled": 22, "skipped": 0, "gone": 0, "already": 0}
    assert out["marked"] == 22
    assert v["surname"] == "EXAMPLE" and v["dob"] == "15/06/1990" and v["sex"] == "F"
    assert v["nationality"] == "CN"                                   # 不是 "China - Hong Kong SAR"
    assert v["maritalStatus"] == "S"
    assert v["ctl00_SiteContentPlaceHolder_FormView1_ddlPPT_ISSUED_DTEDay"] == "05"
    assert v["ctl00_SiteContentPlaceHolder_FormView1_ddlPPT_ISSUED_DTEMonth"] == "3"
    assert v["ctl00_SiteContentPlaceHolder_FormView1_tbxPPT_ISSUEDYear"] == "2020"
    assert v["pptExpiry"] == "2030-03-04" and v["birthCity"] == "Sampletown" and v["homeCity"] == "Testville"
    assert v["homeCountry"] == "already typed by the user"            # 已有内容不覆盖
    assert v["pw"] == "" and v["captchaCode"] == "" and v["purpose"] == "" and v["phone2"] == ""
