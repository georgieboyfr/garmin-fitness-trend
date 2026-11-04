from datetime import date, datetime, timedelta

import numpy as np
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


def test_availability_marks_days_yes_optional_or_no():
    acts = []
    for i, monday in enumerate(mondays(12)):
        acts.append(run(monday, 50))                                 # lundi : 12 semaines sur 12
        if i % 2 == 0:
            acts.append(run(monday + timedelta(days=2), 40))         # mercredi : 6 sur 12
        if i % 3 == 0:
            acts.append(run(monday + timedelta(days=5), 120))        # samedi : 4 sur 12
        if i == 0:
            acts.append(run(monday + timedelta(days=1), 30))         # mardi : 1 sur 12
    acts.append(run(TODAY, 30))                                      # semaine en cours : ignorée
    a = coach.availability_from_history(acts, TODAY)
    by = {d["weekday"]: d for d in a["days"]}
    assert by[0]["status"] == "oui" and by[0]["weeks"] == 12 and by[0]["usual_min"] == 50
    assert by[2]["status"] == "oui" and by[2]["share"] == 0.5         # une semaine sur deux
    assert by[5]["status"] == "optionnel" and by[5]["usual_min"] == 120   # une sur trois
    assert by[1]["status"] == "non" and by[6]["usual_min"] is None
    assert a["sessions_per_week"] == 2


# tracés résumés autour d'un départ commun (45,19 ; 5,73) : 0,001° de latitude ≈ 111 m
HOME = (45.19, 5.73)


def track(*points):
    return np.array([HOME] + [(HOME[0] + dy, HOME[1] + dx) for dy, dx in points] + [HOME])


def test_habit_is_the_farthest_place_most_runs_of_the_day_go_through():
    acts, tracks = [], {}
    summit = (0.008, -0.009)                                         # environ 1,1 km du départ
    for i, monday in enumerate(mondays(26)):
        a = run(monday, 50)
        a["id"] = i
        acts.append(a)
        if i % 4 == 3:
            tracks[i] = track((-0.004, 0.006), (-0.008, 0.012))        # une sur 4 : ailleurs
        elif i % 2:
            tracks[i] = track((0.004, 0.0), summit, (0.0, -0.005))   # montée d'un côté
        else:
            tracks[i] = track((0.0, -0.006), summit, (0.005, 0.002))   # et de l'autre
    habits = coach.habits_from_history(acts, tracks, TODAY)
    assert len(habits) == 1
    h = habits[0]
    assert h["weekday"] == 0 and h["runs"] == 26 and h["count"] >= 19
    assert coach._distance_m(h["place"], (HOME[0] + summit[0], HOME[1] + summit[1])) < 200
    assert h["from_start_m"] > coach.PLACE_START_M


def test_no_habit_when_runs_only_share_the_start():
    acts, tracks = [], {}
    for i, monday in enumerate(mondays(26)):
        a = run(monday, 50)
        a["id"] = i
        acts.append(a)
        angle = i * 0.7
        tracks[i] = track((0.01 * np.sin(angle), 0.01 * np.cos(angle)))   # chaque fois une autre direction
    assert coach.habits_from_history(acts, tracks, TODAY) == []


def test_effective_habits_keep_greg_choice_and_name_for_a_nearby_place():
    detected = [{"weekday": 0, "place": [45.1985, 5.7254], "name": "Grenoble Trail"}]
    stored = [{"weekday": 0, "place": [45.1990, 5.7260], "name": "Bastille", "keep": True}]
    h = coach.effective_habits(stored, detected)[0]
    assert h["keep"] is True and h["confirmed"] and h["label_name"] == "Bastille"
    far = coach.effective_habits([{**stored[0], "place": [45.21, 5.75]}], detected)[0]
    assert not far["confirmed"] and far["label_name"] == "Grenoble Trail"


def test_effective_availability_prefers_what_greg_entered():
    inferred = coach.availability_from_history([run(m, 50) for m in mondays(12)], TODAY)
    auto = coach.effective_availability(None, inferred)
    assert auto[0]["status"] == "oui" and auto[0]["max_min"] == 50 and auto[0]["source"] == "historique"
    assert auto[1]["status"] == "non" and auto[1]["max_min"] is None
    stored = [{"weekday": d, "status": "optionnel" if d == 1 else "non", "max_min": 45 if d == 1 else None}
              for d in range(7)]
    mine = coach.effective_availability(stored, inferred)
    assert mine[0]["status"] == "non" and mine[1]["status"] == "optionnel" and mine[1]["max_min"] == 45
    assert mine[1]["source"] == "saisie"
    legacy = [{"weekday": d, "available": d == 0, "max_min": 50 if d == 0 else None} for d in range(7)]
    old = coach.effective_availability(legacy, inferred)
    assert old[0]["status"] == "oui" and old[1]["status"] == "non"


def test_clean_profile_validates_and_only_returns_sent_fields():
    days = [{"weekday": d, "status": "oui", "max_min": 60} for d in range(7)]
    first = coach.clean_profile({"availability": days})["availability"][0]
    assert first == {"weekday": 0, "status": "oui", "max_min": 60, "every": None}
    assert "habits" not in coach.clean_profile({"availability": days})
    assert coach.clean_profile({"availability": None}) == {"availability": None}
    habit = {"weekday": 0, "place": [45.1985, 5.7254], "name": " Bastille ", "keep": True}
    cleaned = coach.clean_profile({"habits": [habit]})["habits"][0]
    assert cleaned == {"weekday": 0, "place": [45.1985, 5.7254], "name": "Bastille", "keep": True}
    with pytest.raises(ValueError):
        coach.clean_profile({"availability": days[:6]})
    with pytest.raises(ValueError):
        coach.clean_profile({"availability": [{**d, "status": "peut-être"} for d in days]})
    with pytest.raises(ValueError):
        coach.clean_profile({"availability": [{**d, "max_min": 0} for d in days]})
    assert coach.clean_profile({"max_sessions": 4}) == {"max_sessions": 4}
    assert coach.clean_profile({"max_sessions": None}) == {"max_sessions": None}
    with pytest.raises(ValueError):
        coach.clean_profile({"max_sessions": 8})
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
    coach.set_priority(conn, rid, "C")
    assert coach.get(conn, rid)["priority"] == "C"
    with pytest.raises(ValueError):
        coach.set_priority(conn, rid, "D")
    coach.delete(conn, rid)
    assert coach.get(conn, rid) is None


def test_clean_profile_takes_the_two_plan_questions():
    assert coach.clean_profile({"ramp_pct": 15, "long_extension": False}) == {"ramp_pct": 15,
                                                                               "long_extension": False}
    with pytest.raises(ValueError):
        coach.clean_profile({"ramp_pct": 30})


def test_without_an_a_race_the_plan_aims_at_the_next_race():
    races = [{"id": 1, "name": "B", "race_date": "2026-12-06", "priority": "B"},
             {"id": 2, "name": "C", "race_date": "2027-01-10", "priority": "C"},
             {"id": 3, "name": "A passée", "race_date": "2026-10-01", "priority": "A"}]
    cal = coach.calendar(races, TODAY)
    assert cal["main"]["id"] == 1 and cal["conflicts"] == []
    assert coach.calendar([], TODAY)["main"] is None


def test_optional_days_carry_a_frequency():
    days = [{"weekday": d, "status": "oui" if d < 5 else "optionnel", "max_min": 60, "every": 3}
            for d in range(7)]
    cleaned = coach.clean_profile({"availability": days})["availability"]
    assert cleaned[0]["every"] is None and cleaned[5]["every"] == 3
    with pytest.raises(ValueError):
        coach.clean_profile({"availability": [{**d, "every": 6} for d in days]})


def test_clean_periods():
    out = coach.clean_profile({"periods": [
        {"kind": "vacances", "start": "2027-07-10", "end": "2027-07-24", "sessions": 5, "max_min": 120},
        {"kind": "maladie", "start": "2027-01-04", "end": "2027-01-08", "sessions": "", "max_min": None}]})
    assert [p["kind"] for p in out["periods"]] == ["maladie", "vacances"]
    assert out["periods"][0]["sessions"] is None and out["periods"][1]["sessions"] == 5
    assert coach.clean_profile({"periods": []}) == {"periods": None}
    for bad in ({"kind": "fête", "start": "2027-01-01", "end": "2027-01-02"},
                {"kind": "vacances", "start": "2027-07-20", "end": "2027-07-10"},
                {"kind": "vacances", "start": "2027-07-01", "end": "2027-07-10", "sessions": 20}):
        with pytest.raises(ValueError):
            coach.clean_profile({"periods": [bad]})
