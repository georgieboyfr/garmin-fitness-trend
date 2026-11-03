from datetime import date, datetime, timedelta

import pytest

from app import db, settings, tracked
from app.scheduler import DailyScheduler

TODAY = date(2026, 11, 4)            # un mercredi


def eff(key, value, day):
    return {"kind": "distance", "key": key, "value": value, "extra": None, "id": 1, "name": "x", "date": day,
            "year": int(day[:4]), "terrain": "road", "avg_hr": None}


def data(efforts=None):
    acts = [{"id": k, "start": datetime(2026, 8, 1, 9) + timedelta(days=k), "hrss": 50.0} for k in range(100)]
    return {"acts": acts, "efforts": efforts if efforts is not None else [eff(10000, 3000, "2026-07-01")],
            "confirmed": set(), "params": settings.DEFAULTS["elevation"], "lthr": 170}


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    yield c
    c.close()


def road(**kw):
    return {"name": "Semi", "race_date": None, "gpx_id": None, "distance_m": 21097.5, "gain_m": 0.0,
            "target_s": None, **kw}


def test_week_of_is_monday():
    assert tracked.week_of(TODAY) == date(2026, 11, 2)
    assert tracked.week_of(date(2026, 11, 2)) == date(2026, 11, 2)
    assert tracked.week_of(date(2026, 11, 8)) == date(2026, 11, 2)


def test_clean_validates_input(config):
    ok = tracked.clean(config, {"name": " Semi ", "distance_km": "21,1", "gain_m": "",
                                "race_date": "2027-03-14", "target_s": 5400})
    assert ok == {"name": "Semi", "race_date": "2027-03-14", "gpx_id": None, "distance_m": 21100.0,
                  "gain_m": 0.0, "target_s": 5400.0}
    assert tracked.clean(config, {"name": "x", "distance_km": 10, "target_s": ""})["target_s"] is None
    for bad in ({"distance_km": 10}, {"name": "x"}, {"name": "x", "distance_km": -1},
                {"name": "x", "distance_km": 10, "gain_m": "abc"},
                {"name": "x", "distance_km": 10, "race_date": "14/03"},
                {"name": "x", "gpx_id": "0123456789abcdef"},
                {"name": "x", "distance_km": 10, "target_s": -5}, []):
        with pytest.raises(ValueError):
            tracked.clean(config, bad)


def test_record_replays_past_weeks_then_adds_one_per_week(config, conn):
    race_id = tracked.create(conn, road(race_date="2027-03-14", target_s=6500))
    n = tracked.record(config, conn, TODAY, replay_weeks=12, data=data())
    preds = tracked.predictions(conn, race_id)
    assert n == 13 and len(preds) == 13
    assert preds[-1]["week"] == "2026-11-02" and preds[-1]["form_day"] == "2026-11-01"
    assert not preds[-1]["replayed"]
    assert all(p["replayed"] for p in preds[:-1]) and preds[0]["week"] == "2026-08-10"
    assert preds[-1]["optimistic_s"] < preds[-1]["realistic_s"] < preds[-1]["prudent_s"]
    assert preds[-1]["version"] == tracked.VERSION and preds[-1]["fitness"] > 0
    assert tracked.record(config, conn, TODAY, data=data()) == 0              # déjà enregistrée cette semaine
    assert tracked.record(config, conn, TODAY + timedelta(days=7), data=data()) == 1
    s = tracked.summary(config, conn, tracked.get(conn, race_id), TODAY + timedelta(days=7))
    assert s["last"]["week"] == "2026-11-09" and s["before"]["week"] == "2026-10-12"
    assert s["evolution_s"] == round(s["last"]["realistic_s"] - s["before"]["realistic_s"])
    assert s["target_gap_s"] == round(s["last"]["realistic_s"] - 6500) and s["days_left"] == 123
    assert s["route"] == "21,1 km" and s["kind"] == "road" and not s["past"]


def test_record_skips_finished_races_and_weeks_after_the_race(config, conn):
    passed = tracked.create(conn, road(race_date="2026-10-20"))
    linked = tracked.create(conn, road())
    with conn:
        conn.execute("INSERT INTO activities (id, start_time_utc, start_time_local, activity_type,"
                     " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
                     " VALUES (5, 'x', '2026-10-20T09:00:00', 'running', 21100, 6000, 'stored', 'x', 'x')")
        conn.execute("UPDATE tracked_races SET activity_id=5 WHERE id=?", (linked,))
    tracked.record(config, conn, TODAY, replay_weeks=4, data=data())
    weeks = [p["week"] for p in tracked.predictions(conn, passed)]
    assert weeks == ["2026-10-05", "2026-10-12", "2026-10-19"]
    assert tracked.predictions(conn, linked) == []
    assert tracked.record(config, conn, TODAY, data=data(efforts=[])) == 0        # pas d'estimation possible


def test_update_with_new_route_clears_predictions(config, conn):
    race_id = tracked.create(conn, road())
    tracked.record(config, conn, TODAY, replay_weeks=2, data=data())
    assert not tracked.update(conn, race_id, road(name="Semi de Grenoble", target_s=6000))
    assert len(tracked.predictions(conn, race_id)) == 3
    assert tracked.get(conn, race_id)["name"] == "Semi de Grenoble"
    assert tracked.update(conn, race_id, road(distance_m=10000.0))
    assert tracked.predictions(conn, race_id) == []
    with pytest.raises(ValueError):
        tracked.update(conn, 999, road())
    tracked.delete(conn, race_id)
    assert tracked.get(conn, race_id) is None and tracked.all_races(conn) == []


class FakeAccount:
    def __init__(self, configured):
        self.configured = configured

    def is_configured(self):
        return self.configured


class FakeSync:
    running = False


def test_scheduler_records_once_a_week_after_the_daily_sync(config, conn, monkeypatch):
    calls = []
    monkeypatch.setattr(tracked, "record", lambda cfg, c, today, **kw: calls.append(today) or 1)
    sched = DailyScheduler(config, FakeSync(), FakeAccount(True))
    monday = datetime(2026, 11, 9, 5, 0)
    assert sched.weekly(monday) == 0 and calls == []                         # synchro du jour pas faite
    settings.set_state(conn, "garmin_last_auto_day", "2026-11-09")
    assert sched.weekly(datetime(2026, 11, 9, 3, 0)) == 0                     # avant l'heure de la synchro
    assert sched.weekly(monday) == 1 and calls == [date(2026, 11, 9)]
    assert sched.weekly(monday + timedelta(hours=3)) == 0                    # une fois par semaine
    assert DailyScheduler(config, FakeSync(), FakeAccount(False)).weekly(datetime(2026, 11, 17, 5)) == 1
