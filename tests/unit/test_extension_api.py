"""spec 006：给浏览器插件用的本地接口和放行规则。基本信息是虚构的。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
import config
from api.extension import EXTENSION_ID, EXTENSION_ORIGIN
from core.models import PersonalProfile
from core.profile_storage import save_personal_profile
from form_engine.sites import SitePoliciesError, default_site_policies, load_site_policies, policy_for

LOCAL = {"Host": "127.0.0.1:8000"}
EXT = {**LOCAL, "Origin": EXTENSION_ORIGIN}
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "forms"
SCAN = (FIXTURES / "generic-form.scan.json").read_text(encoding="utf-8").strip()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)
    monkeypatch.setattr(app_module, "get_materials_root", lambda: tmp_path)
    save_personal_profile(tmp_path, PersonalProfile.model_validate({
        "identity": {"surname": "EXAMPLE", "date_of_birth": "1990-06-15", "national_id_number": "000000199006150000"},
    }))
    return TestClient(app_module.app)


# ---- 放行规则 ----

def test_extension_can_plan(client):
    r = client.post("/api/ext/plan", headers={**EXT, "Sec-Fetch-Site": "none"}, json={"scan": SCAN})
    assert r.status_code == 200
    body = r.json()
    assert "script" not in body and body["ops"]
    assert {op["i"] for op in body["ops"]} == {x["i"] for x in body["fill"]}


def test_other_origins_blocked(client):
    for origin in ("chrome-extension://abcdefghijklmnopabcdefghijklmnop", "https://evil.example", "http://127.0.0.1:3000"):
        r = client.post("/api/ext/plan", headers={**LOCAL, "Origin": origin}, json={"scan": SCAN})
        assert r.status_code == 403, origin
    # 插件也只能调 /api/ext/ 下的写接口
    assert client.post("/api/tracks", headers=EXT, json={"guide": "schengen-tourist", "title": "x"}).status_code == 403
    # Host 检查照旧（防 DNS 重绑定）
    assert client.post("/api/ext/plan", headers={"Host": "evil.example", "Origin": EXTENSION_ORIGIN},
                       json={"scan": SCAN}).status_code == 403


def test_sensitive_switch(client):
    off = client.post("/api/ext/plan", headers=EXT, json={"scan": SCAN}).json()
    on = client.post("/api/ext/plan", headers=EXT, json={"scan": SCAN, "sensitive": True}).json()
    sens = {"identity.date_of_birth", "identity.national_id_number"}
    assert sens <= {x["path"] for x in off["sensitive"]}
    assert not sens & {x["path"] for x in off["fill"]}
    assert sens <= {x["path"] for x in on["fill"]}


def test_bad_scan_is_422(client):
    r = client.post("/api/ext/plan", headers=EXT, json={"scan": SCAN[:500]})
    assert r.status_code == 422 and "少读" in r.json()["detail"]


def test_status_and_policy(client):
    assert client.get("/api/ext/status", headers=LOCAL).json() == {"ok": True, "extension_id": EXTENSION_ID}
    immi = client.get("/api/ext/site-policy", params={"host": "online.immi.gov.au"}, headers=LOCAL).json()
    assert immi["automation"] == "forbidden" and "4.5" in immi["clause"]
    sub = client.get("/api/ext/site-policy", params={"host": "x.online.immi.gov.au:443"}, headers=LOCAL).json()
    assert sub["automation"] == "forbidden"
    assert client.get("/api/ext/site-policy", params={"host": "example.com"}, headers=LOCAL).json()["automation"] == "unknown"
    assert client.get("/api/ext/site-policy", params={"host": "notonline.immi.gov.au"}, headers=LOCAL).json()["automation"] == "unknown"


# ---- community/site_policies.yaml ----

def test_site_policies_valid():
    sites = default_site_policies()
    assert {s.host for s in sites} >= {"online.immi.gov.au", "ceac.state.gov"}
    assert policy_for("ceac.state.gov", sites)["automation"] == "allowed"


def test_site_policies_checks(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(
        "sites:\n"
        "  - {host: a.example, name: A, automation: forbidden, checked: 2026-09-29}\n"
        "  - {host: b.example, name: B, automation: maybe, checked: 2026-09-29}\n"
        "  - {host: c.example, automation: allowed, checked: 2026-09-29}\n"
        "  - {host: d.example, name: D, automation: allowed, checked: 2026-09-29}\n"
        "  - {host: d.example, name: D2, automation: allowed, checked: 2026-09-29}\n",
        encoding="utf-8",
    )
    with pytest.raises(SitePoliciesError) as e:
        load_site_policies(p)
    msg = str(e.value)
    assert "a.example：forbidden" in msg and "b.example：automation" in msg
    assert "c.example：缺少 name" in msg and "d.example：host 重复" in msg


def test_mcp_plan_has_no_ops():
    from agent_tools import tools
    r = tools.plan_form_fill(SCAN, profile=PersonalProfile())
    assert "ops" not in r and "script" in r


def test_site_date_format(client, tmp_path):
    """2026-09-29 实测：ImmiAccount 的日期框旁边没写格式，框里是 "09 MAR 2002" 这种写法。"""
    immi = policy_for("online.immi.gov.au", default_site_policies())
    assert immi["date_format"] == "dd mmm yyyy"
    scan = ('{"v":1,"host":"online.immi.gov.au","sections":["Passport details"],'
            '"f":[[0,"t","Date of birth",0,"H_input","","off",0,0]]}')
    body = client.post("/api/ext/plan", headers=EXT, json={"scan": scan, "sensitive": True}).json()
    assert body["ops"] == [{"i": 0, "k": "text", "v": "15 JUN 1990"}] and not body["needs_format"]
    other = scan.replace("online.immi.gov.au", "example.com")
    assert client.post("/api/ext/plan", headers=EXT, json={"scan": other, "sensitive": True}).json()["needs_format"]
    bad = tmp_path / "s.yaml"
    bad.write_text("sites:\n  - {host: a.example, name: A, automation: allowed, checked: 2026-09-29, date_format: soon}\n",
                   encoding="utf-8")
    with pytest.raises(SitePoliciesError, match="date_format"):
        load_site_policies(bad)
