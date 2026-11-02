import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, hash_password
from app.main import create_app

from .fake_garmin import MFA_CODE, PASSWORD, FakeGarmin

ADMIN_PASSWORD = "mot-de-passe-admin"
UI = {"X-Requested-With": "admin-ui"}


@pytest.fixture(scope="module")
def admin_hash():
    return hash_password(ADMIN_PASSWORD)


@pytest.fixture
def client(config, admin_hash, monkeypatch):
    monkeypatch.setattr(FakeGarmin, "needs_mfa", False)
    monkeypatch.setattr(FakeGarmin, "fail_token_login", False)
    cfg = dataclasses.replace(config, admin_user="greg", admin_password_hash=admin_hash)
    app = create_app(cfg, garmin_class=lambda: FakeGarmin, sync_options={"sleep": lambda s: None},
                     start_scheduler=False)
    with TestClient(app) as c:
        yield c


def login(client, password=ADMIN_PASSWORD):
    return client.post("/admin/api/login", json={"username": "greg", "password": password})


def test_admin_page_is_served(client):
    r = client.get("/admin")
    assert r.status_code == 200 and "Fitness Trend" in r.text
    assert client.get("/static/admin.js").status_code == 200


def test_admin_disabled_without_hash(config):
    with TestClient(create_app(config, garmin_class=lambda: FakeGarmin)) as c:
        assert c.get("/admin/api/session").json() == {"admin_enabled": False, "authenticated": False}
        assert login(c).status_code == 403
        assert c.get("/admin/api/garmin").status_code == 403


def test_login_sets_httponly_cookie(client):
    assert client.get("/admin/api/garmin").status_code == 401
    r = login(client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Secure" not in cookie  # http en local
    assert client.get("/admin/api/session").json()["authenticated"]
    assert client.get("/admin/api/garmin").status_code == 200


def test_cookie_secure_behind_https_proxy(client):
    r = client.post("/admin/api/login", json={"username": "greg", "password": ADMIN_PASSWORD},
                    headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in r.headers["set-cookie"]


def test_wrong_password_then_throttled(client):
    for _ in range(5):
        assert login(client, "faux").status_code == 401
    r = login(client)  # même le bon mot de passe est refusé pendant le blocage
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_actions_require_csrf_header(client):
    login(client)
    assert client.post("/admin/api/garmin/logout").status_code == 403
    assert client.post("/admin/api/garmin/logout", headers=UI).status_code == 200


def test_logout_closes_session(client):
    login(client)
    client.post("/admin/api/logout")
    assert client.get("/admin/api/garmin").status_code == 401


def test_garmin_login_with_mfa(client, monkeypatch):
    login(client)
    monkeypatch.setattr(FakeGarmin, "needs_mfa", True)
    r = client.post("/admin/api/garmin/login", headers=UI,
                    json={"email": "a@b.c", "password": PASSWORD, "remember": False})
    assert r.json()["state"] == "mfa_pending"
    r = client.post("/admin/api/garmin/mfa", headers=UI, json={"code": "000000"})
    assert r.status_code == 400 and "MFA" in r.json()["detail"]
    r = client.post("/admin/api/garmin/mfa", headers=UI, json={"code": MFA_CODE})
    st = r.json()
    assert st["state"] == "connected" and st["account_name"] == "Camille Test"
    assert not st["password_remembered"]


def test_garmin_wrong_password(client):
    login(client)
    r = client.post("/admin/api/garmin/login", headers=UI,
                    json={"email": "a@b.c", "password": "faux", "remember": True})
    assert r.status_code == 400 and "Garmin a refusé" in r.json()["detail"]
    assert client.get("/admin/api/garmin").json()["state"] == "disconnected"


def connect_garmin(client):
    login(client)
    client.post("/admin/api/garmin/login", headers=UI,
                json={"email": "a@b.c", "password": PASSWORD, "remember": False})


def test_sync_requires_connected_account(client):
    login(client)
    r = client.post("/admin/api/sync", headers=UI, json={})
    assert r.status_code == 400 and "non connecté" in r.json()["detail"]


def test_sync_start_and_status(client):
    connect_garmin(client)
    st = client.get("/admin/api/sync").json()
    assert not st["first_import_done"] and st["counts"]["total"] == 0 and st["runs"] == []
    assert st["settings"] == {"enabled": True, "hour": 4, "history_start": "2015-01-01"}
    assert client.post("/admin/api/sync", headers=UI, json={}).status_code == 202
    deadline = time.monotonic() + 5
    while client.get("/admin/api/sync").json()["running"] and time.monotonic() < deadline:
        time.sleep(0.05)
    st = client.get("/admin/api/sync").json()
    assert not st["running"] and st["first_import_done"]
    assert st["runs"][0]["status"] == "ok" and st["runs"][0]["kind"] == "garmin"


def test_sync_settings(client):
    login(client)
    r = client.post("/admin/api/sync/settings", headers=UI, json={"hour": 6, "enabled": False})
    assert r.json()["hour"] == 6 and not r.json()["enabled"]
    assert client.get("/admin/api/sync").json()["settings"]["hour"] == 6
    r = client.post("/admin/api/sync/settings", headers=UI, json={"hour": 25})
    assert r.status_code == 400


def wait_idle(client):
    deadline = time.monotonic() + 5
    while client.get("/admin/api/sync").json()["running"] and time.monotonic() < deadline:
        time.sleep(0.05)


def test_elevation_status_settings_and_recompute(client):
    login(client)
    st = client.get("/admin/api/elevation").json()
    assert st["pending"] == 0 and st["by_source"] == []
    assert st["settings"]["threshold_dem"] == 4.0
    assert {d["model"]: d["has_barometer"] for d in st["devices"]}["Forerunner 255"] == 1
    r = client.post("/admin/api/elevation/settings", headers=UI, json={"threshold_dem": 5})
    assert r.json()["threshold_dem"] == 5.0
    assert client.post("/admin/api/elevation/settings", headers=UI, json={"window": 4}).status_code == 400
    # recalcul local : possible sans compte Garmin connecté
    assert client.post("/admin/api/recompute", headers=UI).status_code == 202
    wait_idle(client)
    run = client.get("/admin/api/sync").json()["runs"][0]
    assert run["kind"] == "recalcul" and run["status"] == "ok"


def test_garmin_remember_then_forget(client):
    login(client)
    st = client.post("/admin/api/garmin/login", headers=UI,
                     json={"email": "a@b.c", "password": PASSWORD, "remember": True}).json()
    assert st["password_remembered"] and st["password_source"] == "admin"
    st = client.post("/admin/api/garmin/forget-password", headers=UI).json()
    assert not st["password_remembered"] and st["state"] == "connected"
