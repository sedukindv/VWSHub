"""HTTPS origin and cookie boundary. No network, trust import or live server."""
import sys,uuid
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hub.core import create_app


def application(monkeypatch,trusted):
    monkeypatch.setenv("VWSHUB_TRUST_PROXY","1" if trusted else "0")
    monkeypatch.setenv("COOKIE_SECURE","1")
    root=Path(__file__).resolve().parents[2]/".v7-core-tests"/uuid.uuid4().hex
    return create_app(root,{"TESTING":True,"REGISTER_EXTENSIONS":False,"LEGACY_DATA_DIR":root})


@pytest.mark.parametrize("trusted,remote,expected",[(True,"127.0.0.1",200),(True,"::1",200),(True,"203.0.113.9",403),(False,"127.0.0.1",403)])
def test_forwarded_origin_is_only_trusted_from_enabled_loopback(monkeypatch,trusted,remote,expected):
    app=application(monkeypatch,trusted);client=app.test_client()
    headers={"X-Forwarded-Proto":"https","X-Forwarded-Host":"vms.example.test","X-Forwarded-Port":"443"}
    env={"REMOTE_ADDR":remote}
    token=client.get("/api/bootstrap",headers=headers,environ_overrides=env).json["csrf_token"]
    response=client.post("/setup",json={"username":"owner","password":"synthetic-proxy-test-password"},headers={**headers,"Origin":"https://vms.example.test","X-CSRF-Token":token},environ_overrides=env)
    assert response.status_code==expected
    if expected==200:
        assert any("Secure" in cookie and "HttpOnly" in cookie for cookie in response.headers.getlist("Set-Cookie"))


def test_proxy_does_not_disable_csrf_or_cross_origin_checks(monkeypatch):
    app=application(monkeypatch,True);client=app.test_client()
    headers={"X-Forwarded-Proto":"https","X-Forwarded-Host":"vms.example.test","X-Forwarded-Port":"443","Origin":"https://vms.example.test"}
    payload={"username":"owner","password":"synthetic-proxy-test-password"}
    token=client.get("/api/bootstrap",headers=headers).json["csrf_token"]
    assert client.post("/setup",json=payload,headers=headers).status_code==403
    assert client.post("/setup",json=payload,headers={**headers,"X-CSRF-Token":token,"Origin":"https://other.example.test"}).status_code==403
    assert client.post("/setup",json=payload,headers={**headers,"X-CSRF-Token":token}).status_code==200
    policy=client.get("/",headers=headers).headers["Content-Security-Policy"]
    assert "'wasm-unsafe-eval'" in policy and "'unsafe-eval'" not in policy
    assert "connect-src 'self'" in policy and "worker-src 'self' blob:" in policy
