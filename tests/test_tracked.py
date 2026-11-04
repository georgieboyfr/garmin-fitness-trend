from datetime import UTC, date, datetime, timedelta

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


def add_activity(conn, i, day, km, elapsed=6000, name="Semi"):
    with conn:
        conn.execute("INSERT INTO activities (id, start_time_utc, start_time_local, activity_type,"
                     " garmin_name, distance_m, duration_s, fit_status, first_seen_at, updated_at)"
                     " VALUES (?, 'x', ?, 'running', ?, ?, ?, 'stored', 'x', 'x')",
                     (i, day + "T09:00:00", name, km * 1000, elapsed))


def test_link_races_after_the_race(config, conn):
    race_id = tracked.create(conn, road(race_date="2026-10-25", target_s=6200))
    future = tracked.create(conn, road(race_date="2026-12-01"))
    add_activity(conn, 1, "2026-10-25", 10.0)                                # trop courte
    add_activity(conn, 2, "2026-10-25", 21.3, elapsed=6100)
    add_activity(conn, 3, "2026-10-28", 21.1)                                # trois jours après
    tracked.record(config, conn, date(2026, 10, 21), replay_weeks=1, data=data())
    assert tracked.link_races(config, conn, TODAY) == 1
    race = tracked.get(conn, race_id)
    assert race["activity_id"] == 2 and tracked.get(conn, future)["activity_id"] is None
    assert db.connect(config.db_path).execute("SELECT status FROM races WHERE activity_id=2").fetchone()[0] \
        == "confirmed"
    res = tracked.result(conn, race, tracked.predictions(conn, race_id))
    p = res["prediction"]
    assert p["week"] == "2026-10-19" and res["elapsed_s"] == 6100 and res["target_gap_s"] == -100
    assert res["error_pct"] == round((p["realistic_s"] / 6100 - 1) * 100, 1)
    assert [a["id"] for a in tracked.candidates(conn, race)] == [1, 2, 3]
    tracked.set_activity(conn, race_id, None, manual=True)                  # délié à la main
    assert tracked.link_races(config, conn, TODAY) == 0
    assert tracked.summary(config, conn, tracked.get(conn, race_id), TODAY)["result"] is None


def test_proposed_correction_needs_three_races():
    rows = [{"error_pct": 10.0}, {"error_pct": -5.0}, {"error_pct": None}]
    assert tracked._proposal(rows, "error_pct") == {"n": 2, "factor": None, "bias_pct": None}
    rows.append({"error_pct": 4.0})
    mean = (1.10 * 0.95 * 1.04) ** (1 / 3)
    assert tracked._proposal(rows, "error_pct") == {"n": 3, "factor": round(1 / mean, 4),
                                                    "bias_pct": round((mean - 1) * 100, 1)}


def test_corrections_settings_and_display(config, conn):
    assert tracked.corrections(conn) == {"road": 1.0, "trail": 1.0}
    settings.update(conn, "estimator", {"correction_road": 0.96})
    assert tracked.corrections(conn) == {"road": 0.96, "trail": 1.0}
    for bad in ({"correction_road": 1.5}, {"correction_trail": "0.9"}, {"autre": 1},
                {"correction_road": True}):
        with pytest.raises(ValueError):
            settings.update(conn, "estimator", bad)
    race_id = tracked.create(conn, road())
    tracked.record(config, conn, TODAY, data=data())
    raw = tracked.predictions(conn, race_id)[-1]
    s = tracked.summary(config, conn, tracked.get(conn, race_id), TODAY)
    assert s["factor"] == 0.96 and s["last"]["realistic_s"] == round(raw["realistic_s"] * 0.96)


def race_series(config, activity_id, km=10.0, speed=10 / 3, stop_at_m=5000, stop_s=120):
    """Trace d'une course : vitesse constante, une bosse de 100 m au milieu, un arrêt."""
    import json as _json
    import math as _math

    import pyarrow as pa

    from app.fit_parser import SCHEMA
    from app.series import write_series

    t0 = datetime(2026, 10, 25, 7, 0, tzinfo=UTC)
    rows, d, t = [], 0.0, 0.0
    while d <= km * 1000:
        alt = 300 + 100 * _math.sin(_math.pi * d / (km * 1000))
        rows.append((t0 + timedelta(seconds=t), d, 45 + d / 111195, 5.0, alt, 150.0, speed, 85.0))
        if stop_at_m and abs(d - stop_at_m) < 1:
            t += stop_s
            rows.append((t0 + timedelta(seconds=t), d, 45 + d / 111195, 5.0, alt, 120.0, 0.0, 0.0))
        d += 10.0
        t += 10.0 / speed
    cols = list(zip(*rows, strict=True))
    table = pa.table(dict(zip(SCHEMA.names, cols, strict=True)), schema=SCHEMA)
    write_series(config.series_dir, activity_id, table)
    return _json, t - 10.0 / speed            # temps du dernier point


def test_estimate_vs_actual_on_the_race_trace(config, conn, monkeypatch):
    config.series_dir.mkdir(parents=True, exist_ok=True)
    _, total = race_series(config, 500)
    base = data()
    bins = [[-4, 300, 900], [-2, 600, 1800], [0, 600, 1800], [2, 300, 900]]
    import json as _json
    for a in base["acts"]:
        a.update({"grade_bins": _json.dumps(bins), "terrain": "trail", "distance_m": 6000.0})
    race = {"id": 500, "name": "Trail", "start": datetime(2026, 10, 25, 9), "elevation_source": "barometer",
            "elapsed_s": total, "distance_m": 10000.0, "terrain": "trail", "hrss": 80.0}
    base["acts"].append(race)
    monkeypatch.setattr(tracked, "load_data", lambda cfg, c: base)
    r = tracked.estimate_vs_actual(config, conn, 500, TODAY)
    assert [e["key"] for e in r["estimates"]] == ["eve", "today"]
    eve = r["estimates"][0]
    assert eve["day"] == "2026-10-24"
    assert len(r["km"]) == len(r["actual"]) == len(eve["gap"]) == len(r["altitude"])
    assert r["km"][0] == 0 and r["actual"][0] == 0 and r["actual"][-1] == round(total)
    assert eve["gap"][-1] == round(total) - eve["times"][-1]
    assert eve["error_pct"] == round((eve["realistic_s"] / total - 1) * 100, 1)
    i = r["km"].index(5.0)                                                   # l'arrêt se voit dans le réel
    assert r["actual"][i] - r["actual"][i - 1] > 120
    assert max(r["altitude"]) == pytest.approx(400, abs=3)
    assert tracked.estimate_vs_actual(config, conn, 999, TODAY) == {"error": "Sortie inconnue."}
    base["acts"].append({**race, "id": 501})
    assert "error" in tracked.estimate_vs_actual(config, conn, 501, TODAY)    # pas de série



def test_replayed_weeks_are_recomputed_when_the_estimator_changes(config, conn):
    race_id = tracked.create(conn, road())
    tracked.record(config, conn, TODAY, replay_weeks=2, data=data())
    with conn:
        conn.execute("UPDATE tracked_predictions SET version='ancienne', realistic_s=1 WHERE race_id=?",
                     (race_id,))
    assert tracked.record(config, conn, TODAY, data=data()) == 2           # les 2 semaines rejouées
    rows = {p["week"]: p for p in tracked.predictions(conn, race_id)}
    assert rows["2026-10-19"]["version"] == tracked.VERSION and rows["2026-10-19"]["realistic_s"] > 1
    assert rows["2026-11-02"]["version"] == "ancienne"                      # enregistrée en temps réel


def test_ahead_errors_only_count_predictions_recorded_before_the_race():
    def race(err, replayed):
        return {"result": {"error_pct": err, "prediction": {"replayed": replayed}}}
    assert tracked.ahead_errors([race(5.0, 1), {"result": None}]) is None
    s = tracked.ahead_errors([race(5.0, 1), race(-3.0, 0), race(1.0, 0)])
    assert {k: s[k] for k in ("n", "mae_pct", "bias_pct")} == {"n": 2, "mae_pct": 2.0, "bias_pct": -1.0}
