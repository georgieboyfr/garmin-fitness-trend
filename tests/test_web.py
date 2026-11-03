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


def test_volume_page(client, config):
    login(client)
    for terrain in ("all", "road", "trail", "nimporte"):
        r = client.get(f"/volume?terrain={terrain}")
        assert r.status_code == 200 and "Volume et régularité" in r.text
    assert client.get("/volume", follow_redirects=False).status_code == 200


def test_sorties_page(client, config):
    conn = db.connect(config.db_path)
    with conn:
        for i in range(30):
            conn.execute(
                "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
                " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
                " VALUES (?, ?, ?, 'running', ?, 10000, 3000, 'stored', ?, ?)",
                (100 + i, NOW, f"2026-02-{1 + i % 28:02d}T09:00:00", f"Course {i}", NOW, NOW))
    conn.close()
    login(client)
    r = client.get("/sorties")
    assert r.status_code == 200 and "30 sortie(s)" in r.text and "Page 1 / 2" in r.text
    r = client.get("/sorties?page=2&sort=distance&order=asc&year=2026&terrain=all&q=course")
    assert r.status_code == 200 and "Page 2 / 2" in r.text
    r = client.get("/sorties?q=introuvable&year=1999&sort=pirate&order=x")
    assert "Aucune sortie" in r.text


def test_performance_page(client):
    login(client)
    for q in ("", "?terrain=trail", "?terrain=road&year=2026", "?terrain=x&year=abc"):
        r = client.get("/performance" + q)
        assert r.status_code == 200 and "Courbe allure-durée" in r.text


def test_forme_page(client):
    login(client)
    r = client.get("/forme")
    assert r.status_code == 200 and "Efficiency Factor" in r.text


def test_activity_page(client, config):
    conn = db.connect(config.db_path)
    with conn:
        conn.execute(
            "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
            " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
            " VALUES (55, ?, '2026-03-01T09:00:00', 'running', 'Bastille', 8000, 3000, 'stored', ?, ?)",
            (NOW, NOW, NOW))
    conn.close()
    login(client)
    r = client.get("/sorties/55")
    assert r.status_code == 200 and "Bastille" in r.text and "Par kilomètre" not in r.text   # pas de série
    assert client.get("/sorties/999").status_code == 404
    assert client.get("/sorties/55", cookies={}).status_code == 200


def test_courses_page_and_race_toggle(client, config):
    conn = db.connect(config.db_path)
    with conn:
        conn.execute(
            "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
            " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
            " VALUES (77, ?, '2026-03-01T09:00:00', 'running', 'Semi de Grenoble', 21100, 6000, 'stored',"
            " ?, ?)",
            (NOW, NOW, NOW))
    conn.close()
    login(client)
    assert "Aucune course confirmée" in client.get("/courses").text
    ui = {"X-Requested-With": "admin-ui"}
    assert client.post("/admin/api/races/77", headers=ui, json={"status": "confirmed"}).status_code == 200
    r = client.get("/courses")
    assert r.status_code == 200 and "Semi de Grenoble" in r.text
    assert "badge-race" in client.get("/sorties/77").text
    st = client.get("/admin/api/races").json()
    assert [x["id"] for x in st["confirmed"]] == [77]
    client.post("/admin/api/races/77", headers=ui, json={"status": "rejected"})
    st = client.get("/admin/api/races").json()
    assert [x["id"] for x in st["rejected"]] == [77] and st["confirmed"] == []
    client.post("/admin/api/races/77", headers=ui, json={"status": "confirmed"})       # on revient dessus
    assert client.post("/admin/api/races/settings", headers=ui, json={"threshold": 99}).status_code == 400
    st = client.post("/admin/api/races/settings", headers=ui,
                     json={"keywords": ["Trail Du"], "threshold": 4}).json()
    assert st["settings"]["keywords"] == ["trail du"] and st["settings"]["custom_keywords"]
