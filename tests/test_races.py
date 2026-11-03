from datetime import datetime

import pytest

from app import courses, db, races


def act(i, day, km, moving, avg_hr=140, name="Sortie", terrain="road", hrss=60, start_pos=(45.19, 5.72),
        elapsed=None, description=None):
    return {"id": i, "start": datetime.fromisoformat(day), "distance_km": km, "moving_duration_s": moving,
            "elapsed_s": elapsed or moving + 120, "avg_hr": avg_hr, "name": name, "description": description,
            "terrain": terrain, "hrss": hrss, "start_pos": start_pos, "gain_m": 50}


def usual_runs():
    # 20 sorties habituelles : 10 km en 55 min, FC 140, en semaine à midi, chez soi
    return [act(100 + i, f"2026-03-{2 + i:02d}T12:00:00", 10, 3300) for i in range(20)]


def test_keyword_match():
    assert races.keyword_match("Semi-marathon de Grenoble", races.DEFAULT_KEYWORDS) == "marathon"
    assert races.keyword_match("Trail du Néron", races.DEFAULT_KEYWORDS) == "trail du"
    assert races.keyword_match("Sortie semis de printemps", ["semi"]) is None     # mot entier seulement
    assert races.keyword_match(None, races.DEFAULT_KEYWORDS) is None


def test_real_race_scores_high_and_easy_run_low():
    acts = usual_runs()
    race = act(1, "2026-04-12T09:00:00", 10.05, 2700, avg_hr=172, name="10 km de Grenoble", hrss=110,
               elapsed=2710)
    away = act(2, "2026-05-17T08:30:00", 21.1, 6000, avg_hr=165, name="Course à pied le matin", hrss=180,
               start_pos=(44.9, 5.2), elapsed=6010)
    acts += [race, away]
    found = {c["id"]: c for c in races.candidates(acts, [], lthr=178, keywords=races.DEFAULT_KEYWORDS,
                                                  threshold=5)}
    assert 1 in found and 2 in found
    assert any("10 km de" in r for r in found[1]["reasons"])
    assert any("distance ronde" in r for r in found[2]["reasons"])
    assert any("loin" in r for r in found[2]["reasons"])
    assert not set(found) & {a["id"] for a in usual_runs()}


def test_home_location():
    starts = [(45.19, 5.72)] * 10 + [(44.0, 4.0)]
    assert races.home_location(starts) == (45.19, 5.72)
    assert races.home_location([None]) is None


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    c.execute("INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, fit_status,"
              " first_seen_at, updated_at)"
              " VALUES (5, 'x', '2026-03-01T09:00:00', 'running', 'stored', 'x', 'x')")
    c.commit()
    yield c
    c.close()


def test_decide(conn):
    courses.decide(conn, 5, "confirmed")
    assert conn.execute("SELECT status FROM races").fetchone()[0] == "confirmed"
    courses.decide(conn, 5, "rejected")
    assert conn.execute("SELECT status FROM races").fetchone()[0] == "rejected"
    courses.decide(conn, 5, None)
    assert conn.execute("SELECT COUNT(*) FROM races").fetchone()[0] == 0
    with pytest.raises(ValueError):
        courses.decide(conn, 5, "peut-être")
    with pytest.raises(ValueError):
        courses.decide(conn, 999, "confirmed")


def test_overview_and_page_empty(conn, config):
    from datetime import date

    o = courses.overview(config, conn)
    assert o["pending"] == [] and o["settings"]["threshold"] == 5
    assert o["settings"]["keywords"] == races.DEFAULT_KEYWORDS and not o["settings"]["custom_keywords"]
    assert courses.race_page(config, conn, date(2026, 11, 3)) == {"races": []}
