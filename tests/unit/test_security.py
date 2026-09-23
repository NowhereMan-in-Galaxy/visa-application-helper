"""防跨站请求（CSRF）/ DNS 重绑定中间件（`api.app.anti_csrf`）的测试。

Track 写到临时目录（`get_materials_root` 打了 monkeypatch），不碰真实的材料根目录。
"""

import pytest
from fastapi.testclient import TestClient

import api.app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "get_materials_root", lambda: tmp_path)
    return TestClient(app_module.app)


# ---------- 规则 1：Host 白名单（防 DNS 重绑定），GET/HEAD/OPTIONS 也要挡 ----------


def test_get_with_evil_host_rejected(client):
    resp = client.get("/api/guides", headers={"Host": "evil.example"})
    assert resp.status_code == 403
    assert "detail" in resp.json()
    assert isinstance(resp.json()["detail"], str) and resp.json()["detail"]


def test_get_with_default_testserver_host_allowed(client):
    # TestClient 默认发的 Host 就是 testserver，白名单里必须留一条给它，否则现有 100+ 个测试全挂。
    resp = client.get("/api/guides")
    assert resp.status_code == 200


def test_get_with_localhost_and_port_allowed(client):
    resp = client.get("/api/guides", headers={"Host": "localhost:8000"})
    assert resp.status_code == 200


def test_get_with_ipv6_loopback_host_allowed(client):
    resp = client.get("/api/guides", headers={"Host": "[::1]:8000"})
    assert resp.status_code == 200


# ---------- 规则 2：写请求的 Origin 校验 ----------


def test_post_cross_site_origin_rejected(client):
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403
    assert "Origin" in resp.json()["detail"]


def test_post_same_origin_allowed(client):
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200


def test_post_same_origin_with_explicit_default_port_allowed(client):
    # Origin 里的 :80 和 Host 里没写端口，按 http 默认端口算，应该判成同一个源。
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1:80"},
    )
    assert resp.status_code == 200


def test_post_localhost_and_127_are_different_origins(client):
    # localhost 和 127.0.0.1 虽然都指向本机，但主机名不同，必须算跨源。
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Host": "127.0.0.1", "Origin": "http://localhost"},
    )
    assert resp.status_code == 403


# ---------- 规则 2：写请求的 Sec-Fetch-Site 校验 ----------


def test_post_sec_fetch_site_cross_site_rejected(client):
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert resp.status_code == 403
    assert "Sec-Fetch-Site" in resp.json()["detail"]


def test_post_sec_fetch_site_same_site_rejected(client):
    # localhost:3000 打 localhost:8000 这种"同域名不同端口"，浏览器标的就是 same-site 而不是
    # same-origin，同样要拦——不能只挡 cross-site。
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Sec-Fetch-Site": "same-site"},
    )
    assert resp.status_code == 403


def test_post_sec_fetch_site_same_origin_allowed(client):
    resp = client.post(
        "/api/tracks",
        json={"guide": "schengen-tourist"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert resp.status_code == 200


# ---------- 规则 2：两个头都没有 → 放行（curl / TestClient / 本机 Agent 进程） ----------


def test_post_without_origin_or_sec_fetch_site_allowed(client):
    resp = client.post("/api/tracks", json={"guide": "schengen-tourist"})
    assert resp.status_code == 200


# ---------- 规则 3：只读方法不做 Origin / Sec-Fetch-Site 校验 ----------


def test_get_cross_site_origin_not_rejected_by_origin_rule(client):
    # GET 是安全方法，规则 2 不适用；带一个跨站 Origin 也应该正常返回。
    resp = client.get("/api/guides", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 200
