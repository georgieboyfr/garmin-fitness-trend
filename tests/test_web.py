import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth import hash_password
from app.main import create_app

PASSWORD = "mot-de-passe-admin"
NOW = "2026-03-01T08:00:00Z"


@pytest.fixture(scope="module")
def admin_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def client(config, admin_hash):
    cfg = dataclasses.replace(config, admin_user="greg", admin_password_hash=admin_hash)
    with TestClient(create_app(cfg, start_scheduler=False)) as c:
        yield c


def login(client):
    assert client.post("/admin/api/login", json={"username": "greg", "password": PASSWORD}).status_code == 200


def test_pages_require_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin?next=/"


def test_session_cookie_covers_whole_site(client):
    r = client.post("/admin/api/login", json={"username": "greg", "password": PASSWORD})
    assert "Path=/;" in r.headers["set-cookie"] or r.headers["set-cookie"].endswith("Path=/")


def test_home_empty_database(client):
    login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "à ce jour" in r.text and "Distance cumulée" in r.text


def test_home_with_activities(client, config):
    conn = db.connect(config.db_path)
    with conn:
        conn.execute(
            "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
            " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
            " VALUES (1, ?, '2026-03-01T09:00:00', 'trail_running', 'Bastille', 12000, 4000, 'stored', ?, ?)",
            (NOW, NOW, NOW))
        conn.execute(
            "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
            " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
            " VALUES (2, ?, '2026-03-02T09:00:00', 'lap_swimming', 'Piscine', 1500, 2000, 'stored', ?, ?)",
            (NOW, NOW, NOW))
    conn.close()
    login(client)
    r = client.get("/")
    assert "Bastille" in r.text           # dernière sortie de course
    assert "Piscine" not in r.text        # la natation ne compte pas
