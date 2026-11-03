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
    assert r.status_code == 200 and "30 sortie(s)" in r.text and "<strong>1–30</strong> sur 30" in r.text
    # nombre par page choisi, puis mémorisé dans un cookie
    r = client.get("/sorties?per_page=25")
    assert "page 1 / 2" in r.text and r.cookies.get("per_page") == "25"
    r = client.get("/sorties?page=2&sort=distance&order=asc&year=2026&terrain=all&q=course")
    assert r.status_code == 200 and "page 2 / 2" in r.text and "<strong>26–30</strong> sur 30" in r.text
    r = client.get("/sorties?per_page=7")                              # taille inconnue : dernier choix gardé
    assert "page 1 / 2" in r.text
    r = client.get("/sorties?dmin=5&dmax=12,5&gmin=abc&gmax=-3")
    assert "30 sortie(s)" in r.text and 'name="dmax" value="12.5"' in r.text
    assert 'name="gmin" value=""' in r.text and 'name="gmax" value=""' in r.text
    assert "0 sortie(s)" in client.get("/sorties?dmin=11").text
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


def test_estimateur_page(client):
    login(client)
    for q in ("", "?distance=10", "?distance=12,5&gain=150", "?distance=abc"):
        r = client.get("/estimateur" + q)
        assert r.status_code == 200 and "Forme actuelle" in r.text
    assert 'href="/estimateur"' in client.get("/").text


def test_estimateur_periods_are_remembered(client):
    login(client)
    r = client.get("/estimateur?weeks=6&months=24")
    assert r.status_code == 200 and r.cookies.get("estimateur") == "6-24"
    assert '<option value="6" selected>6 semaines' in r.text
    r = client.get("/estimateur")
    assert '<option value="24" selected>2 ans' in r.text
    r = client.get("/estimateur?weeks=5&months=7")                     # valeurs refusées : dernier choix
    assert '<option value="6" selected>6 semaines' in r.text


def test_estimateur_gpx_upload(client, config):
    pts = "".join(f'<trkpt lat="{45 + i * 20 / 111195}" lon="5"><ele>{i * 2}</ele></trkpt>'
                  for i in range(200))
    data = f'<gpx><trk><trkseg>{pts}</trkseg></trk></gpx>'.encode()
    assert client.post("/estimateur/gpx", content=data).status_code == 401
    login(client)
    assert client.post("/estimateur/gpx", content=b"pas un gpx").status_code == 400
    r = client.post("/estimateur/gpx", content=data, headers={"X-Filename": "Trail%20du%20Vercors.gpx"})
    assert r.status_code == 200
    gpx_id = r.json()["id"]
    assert (config.gpx_dir / f"{gpx_id}.gpx").read_bytes() == data
    page = client.get(f"/estimateur?gpx={gpx_id}")
    assert page.status_code == 200 and "Trail du Vercors" in page.text
    assert "modèle allure-pente" in page.text                     # base vide : message d'erreur affiché
    assert client.get("/estimateur?gpx=../../etc").status_code == 200
