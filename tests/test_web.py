import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth import hash_password
from app.main import create_app

PASSWORD = "mot-de-passe-admin"


class NoDem:
    """MNT injoignable : les GPX gardent leur propre altitude."""

    def elevations(self, lats, lons):
        from app.dem import DemUnavailable
        raise DemUnavailable("hors ligne")
NOW = "2026-03-01T08:00:00Z"


@pytest.fixture(scope="module")
def admin_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def client(config, admin_hash):
    cfg = dataclasses.replace(config, admin_user="greg", admin_password_hash=admin_hash)
    with TestClient(create_app(cfg, start_scheduler=False, dem_factory=NoDem)) as c:
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
    assert "Aucune course trail confirmée" in r.text
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


def test_estimateur_aid_stations(client, config):
    pts = "".join(f'<trkpt lat="{45 + i * 20 / 111195}" lon="5"><ele>{i * 2}</ele></trkpt>'
                  for i in range(200))
    wpt = f'<wpt lat="{45 + 2000 / 111195}" lon="5"><name>Ravito du col</name></wpt>'
    login(client)
    data = f"<gpx>{wpt}<trk><trkseg>{pts}</trkseg></trk></gpx>".encode()
    gpx_id = client.post("/estimateur/gpx", content=data).json()["id"]
    gpx_page = client.get(f"/estimateur?gpx={gpx_id}")
    assert gpx_page.status_code == 200
    assert gpx_page.text.count("Ravito du col") == 1             # proposé d'après le waypoint (éditeur)
    url = f"/estimateur/gpx/{gpx_id}/ravitos"
    assert client.post(url, json=[{"km": -2}]).status_code == 400
    assert client.post(url, content=b"{pas du json").status_code == 400
    assert client.post("/estimateur/gpx/0123456789abcdef/ravitos", json=[]).status_code == 404
    r = client.post(url, json=[{"km": 3.2, "name": "Buvette", "stop_min": 4}])
    assert r.status_code == 200
    assert r.json()["aid_stations"] == [{"km": 3.2, "name": "Buvette", "stop_min": 4.0}]
    meta = json.loads((config.gpx_dir / f"{gpx_id}.json").read_text(encoding="utf-8"))
    assert meta["aid_stations"][0]["name"] == "Buvette" and meta["name"] == "Parcours"
    text = client.get(f"/estimateur?gpx={gpx_id}").text
    assert "Buvette" in text and "Ravito du col" not in text
    assert client.post(url, json=[]).status_code == 200            # tout retirer : plus de proposition
    assert "Ravito du col" not in client.get(f"/estimateur?gpx={gpx_id}").text
    client.cookies.clear()
    assert client.post(url, json=[]).status_code == 401


def test_tracked_races_pages(client):
    body = {"name": "Semi de Grenoble", "distance_km": "21,1", "gain_m": "", "race_date": "2027-03-14",
            "target_s": 5400}
    assert client.post("/estimateur/courses", json=body).status_code == 401
    login(client)
    assert client.post("/estimateur/courses", json={"name": ""}).status_code == 400
    r = client.post("/estimateur/courses", json=body)
    assert r.status_code == 200
    race_id = r.json()["id"]
    page = client.get(f"/estimateur/courses/{race_id}")
    assert page.status_code == 200 and "Semi de Grenoble" in page.text
    assert "Pas encore de prédiction" in page.text                     # base vide : aucun effort route
    assert "Semi de Grenoble" in client.get("/estimateur").text
    r = client.post(f"/estimateur/courses/{race_id}", json={**body, "name": "Semi"})
    assert r.status_code == 200 and "Semi" in client.get(f"/estimateur/courses/{race_id}").text
    assert client.post("/estimateur/courses/999", json=body).status_code == 404
    assert client.get("/estimateur/courses/999").status_code == 404
    assert client.post(f"/estimateur/courses/{race_id}/supprimer").status_code == 200
    assert client.get(f"/estimateur/courses/{race_id}").status_code == 404


def test_tracked_race_manual_link_and_calibration_admin(client, config):
    login(client)
    race_id = client.post("/estimateur/courses", json={"name": "Semi", "distance_km": 21.1,
                                                       "race_date": "2026-02-28"}).json()["id"]
    conn = db.connect(config.db_path)
    with conn:
        conn.execute(
            "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
            " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
            " VALUES (88, ?, '2026-03-01T09:00:00', 'running', 'Semi de Paris', 30000, 9000, 'stored', ?, ?)",
            (NOW, NOW, NOW))
    conn.close()
    page = client.get(f"/estimateur/courses/{race_id}").text            # 30 km : pas reliée d'office
    assert "Semi de Paris" in page and "Temps réel" not in page
    url = f"/estimateur/courses/{race_id}/sortie"
    assert client.post(url, json={"activity_id": 999}).status_code == 400
    assert client.post(url, json={"activity_id": "abc"}).status_code == 400
    assert client.post(url, json={"activity_id": 88}).status_code == 200
    page = client.get(f"/estimateur/courses/{race_id}").text
    assert "Temps réel" in page and "Comparer l'estimé et le réel" in page
    assert client.post(url, json={"activity_id": None}).status_code == 200
    ui = {"X-Requested-With": "admin-ui"}
    st = client.get("/admin/api/estimator").json()
    assert st["applied"] == {"correction_road": None, "correction_trail": None}
    assert st["proposed"]["road"]["factor"] is None
    assert client.post("/admin/api/estimator", headers=ui, json={"correction_road": 3}).status_code == 400
    st = client.post("/admin/api/estimator", headers=ui, json={"correction_road": 0.97}).json()
    assert st["applied"]["correction_road"] == 0.97
    assert "Correction en vigueur" in client.get("/estimateur").text


def test_estimate_vs_actual_endpoint(client, config):
    conn = db.connect(config.db_path)
    with conn:
        conn.execute(
            "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
            " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
            " VALUES (66, ?, '2026-03-01T09:00:00', 'running', 'Trail', 10000, 4000, 'stored', ?, ?)",
            (NOW, NOW, NOW))
    conn.close()
    assert client.get("/sorties/66/estime-reel").status_code == 401
    login(client)
    r = client.get("/sorties/66/estime-reel")
    assert r.status_code == 400 and "trace" in r.json()["error"]



def test_coach_this_week_page(client, config):
    from datetime import date, timedelta

    from app import coach
    conn = db.connect(config.db_path)
    with conn:
        day = (date.today() + timedelta(weeks=12)).isoformat()
        coach.create(conn, {"name": "Semi du lac", "race_date": day,
                            "priority": "A", "gpx_id": None, "distance_m": 21100.0, "gain_m": 0.0,
                            "target_s": 6300.0})
    conn.close()
    login(client)
    r = client.get("/coach")                       # vue par défaut avec une course A
    assert r.status_code == 200
    assert "Cette semaine" in r.text and "Séances faites" in r.text and "Semi du lac" in r.text
    assert "dans 12 semaines" in r.text
    r = client.get("/coach?vue=plan")
    assert r.status_code == 200 and "Ton plan" in r.text


def test_coach_review_answers_and_notification_settings(client, config):
    ui = {"X-Requested-With": "admin-ui"}
    assert client.post("/coach/bilan/2026-11-02", json={"feeling": "fatigué"}).status_code == 401
    login(client)
    assert client.post("/coach/bilan/2026-11-03", json={"feeling": "fatigué"}).status_code == 400  # un mardi
    assert client.post("/coach/bilan/2026-11-02", json={"feeling": "épuisé"}).status_code == 400
    r = client.post("/coach/bilan/2026-11-02", json={"next_week": "chargée", "feeling": "fatigué"})
    assert r.status_code == 200
    from app import coach_review
    conn = db.connect(config.db_path)
    row = coach_review.all_reviews(conn)["2026-11-02"]
    conn.close()
    assert row["next_week"] == "chargée" and row["feeling"] == "fatigué"

    st = client.get("/admin/api/notifications").json()
    assert st == {"settings": {"review_enabled": True, "review_hour": 19, "public_url": None},
                  "configured": False}
    st = client.post("/admin/api/notifications", headers=ui,
                     json={"review_hour": 20, "public_url": "https://trend.example/"}).json()
    assert st["settings"]["review_hour"] == 20 and st["settings"]["public_url"] == "https://trend.example"
    r = client.post("/admin/api/notifications", headers=ui, json={"public_url": "ftp://x"})
    assert r.status_code == 400
    r = client.post("/admin/api/notifications/test", headers=ui, json={})
    assert r.status_code == 400 and "NTFY_URL" in r.json()["detail"]


def test_coach_page_shows_the_sunday_review(client, config, monkeypatch):
    from datetime import date

    from app import coach, settings, web
    monkeypatch.setattr(web, "_today", lambda request: date(2026, 11, 8))           # un dimanche
    conn = db.connect(config.db_path)
    with conn:
        race_id = coach.create(conn, {"name": "Semi du lac", "race_date": "2027-02-14", "priority": "A",
                                      "gpx_id": None, "distance_m": 21100.0, "gain_m": 0.0,
                                      "target_s": 6300.0})
        conn.execute("UPDATE coach_races SET created_at='2026-11-02T08:00:00' WHERE id=?", (race_id,))
    days = [{"weekday": d, "status": "oui" if d in (1, 3, 5) else "non", "max_min": 60} for d in range(7)]
    settings.update(conn, "coach", {"availability": days})
    conn.close()
    login(client)
    r = client.get("/coach?vue=semaine")
    assert r.status_code == 200
    assert "Bilan de la semaine" in r.text and 'data-url="/coach/bilan/2026-11-02"' in r.text
    assert "Semaine peu suivie" in r.text and "La semaine prochaine" in r.text
    r = client.post("/coach/bilan/2026-11-02", json={"next_week": "chargée", "feeling": None})
    assert r.status_code == 200
    r = client.get("/coach?vue=plan")
    assert r.status_code == 200 and "Semaine chargée" in r.text
