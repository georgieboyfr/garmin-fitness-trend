from datetime import date, datetime, timedelta

import pytest

from app import coach

TODAY = date(2026, 11, 4)          # mercredi


def run(day: date, minutes=60, route=None, hour=8, km=10.0):
    return {"id": hash((day, hour)) % 10**9, "start": datetime(day.year, day.month, day.day, hour),
            "moving_duration_s": minutes * 60, "route_id": route, "name": "Sortie", "distance_km": km,
            "gain_m": 100.0}


def mondays(weeks):
    first = TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=weeks)
    return [first + timedelta(weeks=w) for w in range(weeks)]


def test_availability_marks_days_run_at_least_one_week_in_two():
    acts = []
    for i, monday in enumerate(mondays(12)):
        acts.append(run(monday, 50, route=7))                        # lundi : 12 semaines sur 12
        if i % 2 == 0:
            acts.append(run(monday + timedelta(days=2), 40))         # mercredi : 6 sur 12
        if i % 3 == 0:
            acts.append(run(monday + timedelta(days=5), 120))        # samedi : 4 sur 12
    acts.append(run(TODAY, 30))                                      # semaine en cours : ignorée
    a = coach.availability_from_history(acts, TODAY)
    by = {d["weekday"]: d for d in a["days"]}
    assert by[0]["habitual"] and by[0]["weeks"] == 12 and by[0]["usual_min"] == 50
    assert by[2]["habitual"] and by[2]["share"] == 0.5                # une semaine sur deux : habituel
    assert not by[5]["habitual"] and by[5]["usual_min"] == 120
    assert not by[1]["habitual"] and by[1]["usual_min"] is None
    assert a["sessions_per_week"] == 2


def test_habits_need_a_route_making_half_the_runs_of_a_habitual_day():
    acts = []
    for i, monday in enumerate(mondays(12)):
        acts.append(run(monday, 50, route=7 if i % 4 else 9))         # lundi : parcours 7 trois fois sur 4
        acts.append(run(monday + timedelta(days=3), 45, route=i))     # jeudi : parcours toujours différent
    habits = coach.habits_from_history(acts, TODAY)
    assert [(h["weekday"], h["route_id"], h["count"], h["runs"]) for h in habits] == [(0, 7, 9, 12)]


def test_effective_availability_prefers_what_greg_entered():
    inferred = coach.availability_from_history([run(m, 50) for m in mondays(12)], TODAY)
    auto = coach.effective_availability(None, inferred)
    assert auto[0]["available"] and auto[0]["max_min"] == 50 and auto[0]["source"] == "historique"
    assert not auto[1]["available"] and auto[1]["max_min"] is None
    stored = [{"weekday": d, "available": d == 1, "max_min": 45 if d == 1 else None} for d in range(7)]
    mine = coach.effective_availability(stored, inferred)
    assert not mine[0]["available"] and mine[1]["available"] and mine[1]["max_min"] == 45
    assert mine[1]["source"] == "saisie"


def test_clean_profile_validates_and_only_returns_sent_fields():
    days = [{"weekday": d, "available": True, "max_min": 60} for d in range(7)]
    assert coach.clean_profile({"availability": days})["availability"][0] == \
        {"weekday": 0, "available": True, "max_min": 60}
    assert "habits" not in coach.clean_profile({"availability": days})
    assert coach.clean_profile({"availability": None}) == {"availability": None}
    assert coach.clean_profile({"habits": [{"weekday": 0, "route_id": 7, "keep": True}]}) == \
        {"habits": [{"weekday": 0, "route_id": 7, "keep": True}]}
    with pytest.raises(ValueError):
        coach.clean_profile({"availability": days[:6]})
    with pytest.raises(ValueError):
        coach.clean_profile({"availability": [{**d, "max_min": 0} for d in days]})
    with pytest.raises(ValueError):
        coach.clean_profile({})


def test_clean_requires_a_date_and_a_priority(tmp_path):
    cfg = type("Cfg", (), {"gpx_dir": tmp_path})()
    base = {"name": "Semi", "distance_km": "21,1", "race_date": "2027-03-14"}
    assert coach.clean(cfg, {**base, "priority": "a"})["priority"] == "A"
    with pytest.raises(ValueError, match="date"):
        coach.clean(cfg, {**base, "race_date": None, "priority": "A"})
    with pytest.raises(ValueError, match="priorité"):
        coach.clean(cfg, {**base, "priority": "D"})


def test_calendar_splits_upcoming_and_past_and_finds_the_main_race():
    races = [{"id": 1, "name": "B", "race_date": "2026-12-06", "priority": "B"},
             {"id": 2, "name": "A", "race_date": "2027-04-11", "priority": "A"},
             {"id": 3, "name": "Vieille", "race_date": "2026-10-01", "priority": "C"}]
    cal = coach.calendar(races, TODAY)
    assert [r["id"] for r in cal["upcoming"]] == [1, 2] and [r["id"] for r in cal["past"]] == [3]
    assert cal["main"]["id"] == 2 and cal["upcoming"][0]["days_left"] == 32
    assert cal["upcoming"][0]["weeks_left"] == 4
    assert cal["upcoming"][1]["priority_label"] == "Objectif principal"


def test_coach_races_are_stored(tmp_path):
    from app import db
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    race = {"name": "Trail", "race_date": "2027-06-01", "priority": "A", "gpx_id": None,
            "distance_m": 30000.0, "gain_m": 1500.0, "target_s": None}
    rid = coach.create(conn, race)
    coach.set_target(conn, rid, 12600.0)
    assert coach.get(conn, rid)["target_s"] == 12600.0
    coach.update(conn, rid, {**race, "priority": "B", "target_s": 12000.0})
    assert coach.all_races(conn)[0]["priority"] == "B"
    coach.delete(conn, rid)
    assert coach.get(conn, rid) is None
