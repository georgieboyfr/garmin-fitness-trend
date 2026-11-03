from datetime import date, datetime, timedelta

import pytest

from app import stats


def act(day, km, gain=0.0, moving=3600, name="Sortie"):
    return {"start": datetime.fromisoformat(day + "T12:00:00"), "distance_km": km, "gain_m": gain,
            "moving_duration_s": moving, "duration_s": moving + 60, "name": name}


ACTS = [
    act("2025-01-10", 10, 100), act("2025-03-01", 12, 300), act("2025-11-20", 8, 0),
    act("2026-01-05", 11, 200), act("2026-02-28", 9, 50), act("2026-11-02", 15, 700, name="Bastille"),
]


def test_km_effort():
    assert stats.km_effort(10, 500) == 15


def test_same_day_last_year_handles_29_february():
    assert stats.same_day_last_year(date(2024, 2, 29)) == date(2023, 2, 28)
    assert stats.same_day_last_year(date(2026, 11, 3)) == date(2025, 11, 3)


def test_totals():
    t = stats.totals(ACTS[:2])
    assert t == {"count": 2, "distance_km": 22, "gain_m": 400, "km_effort": 26, "hours": 2}


def test_year_to_date_compares_same_date():
    ytd = stats.year_to_date(ACTS, date(2026, 3, 1))
    assert ytd["current"]["distance_km"] == 20          # 5 janv. + 28 févr.
    assert ytd["previous"]["distance_km"] == 22         # 10 janv. + 1er mars 2025, pas le 20 nov.
    assert ytd["change_pct"]["distance_km"] == pytest.approx(-9.1)
    assert stats.year_to_date([], date(2026, 3, 1))["change_pct"]["distance_km"] is None


def test_cumulative_by_day():
    cum = stats.cumulative_by_day(ACTS, 2026, "distance_km", until=date(2026, 1, 10))
    assert len(cum) == 10
    assert cum[3] == 0 and cum[4] == 11 and cum[-1] == 11


def test_home():
    h = stats.home(ACTS, date(2026, 11, 3))
    assert h["last"]["name"] == "Bastille" and h["last"]["gain_m"] == 700
    assert h["first_year"] == 2025
    assert list(h["cumulative"]) == ["2025", "2026"]
    assert len(h["cumulative"]["2026"]) == 307               # 1er janv. -> 3 nov.
    assert len(h["cumulative"]["2025"]) == 365
    assert h["cumulative"]["2025"][-1] == 30
    assert h["week"]["count"] == 1                           # lundi 2 nov. -> mardi 3 nov.
    assert stats.home([], date(2026, 11, 3))["last"] is None


# ---------- volume et régularité ----------

def test_week_streaks():
    weeks = {date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 2, 2)}
    assert stats.week_streaks(weeks) == [(date(2026, 1, 5), date(2026, 1, 19), 3),
                                         (date(2026, 2, 2), date(2026, 2, 2), 1)]


def test_regularity():
    acts = [act(d, 5) for d in ("2026-10-12", "2026-10-21", "2026-10-28", "2026-11-02", "2025-12-30")]
    r = stats.regularity(acts, date(2026, 11, 3))
    assert r["current_weeks"] == 4            # semaines du 12, 19, 26 oct. et 2 nov.
    assert r["longest"]["weeks"] == 4
    assert r["active_weeks_this_year"] == 4
    assert r["elapsed_weeks_this_year"] == 45
    # pas de sortie cette semaine ni la précédente : série interrompue
    assert stats.regularity(acts, date(2026, 11, 25))["current_weeks"] == 0


def test_yearly_table_and_terrain_filter():
    acts = [dict(act("2026-01-05", 10, 300), terrain="trail"), dict(act("2026-01-06", 10, 0), terrain="road"),
            dict(act("2026-01-07", 8, 0), terrain="indoor"), dict(act("2025-03-01", 12, 120), terrain="road")]
    rows = stats.yearly_table(acts)
    assert [r["year"] for r in rows] == [2025, 2026]
    assert rows[1]["distance_km"] == 28 and rows[1]["gain_per_km"] == pytest.approx(10.7)
    assert rows[1]["active_weeks"] == 1 and rows[1]["longest_streak"] == 1
    assert len(stats.filter_terrain(acts, "trail")) == 1
    assert len(stats.filter_terrain(acts, "road")) == 3       # le tapis compte comme route
    assert stats.filter_terrain(acts, "all") is acts


def test_volume_payload():
    v = stats.volume(ACTS, date(2026, 11, 3))
    assert set(v["cumulative"]) == {"distance_km", "gain_m", "km_effort"}
    assert v["cumulative"]["km_effort"]["2026"][-1] == pytest.approx(35 + 9.5)
    assert v["monthly"]["distance_km"]["2025"][2] == 12
    assert v["calendar"]["2026-11-02"] == {"km": 15, "gain": 700, "names": ["Bastille"]}
    assert v["years"] == [2025, 2026]


# ---------- liste des sorties ----------

def _list_acts():
    out = []
    for i in range(60):
        a = act(f"2025-{1 + i % 12:02d}-{1 + i // 12:02d}", 5 + i % 7, gain=i * 10, moving=1800 + i * 10,
                name=f"Sortie {i}")
        a.update(id=i, description="avec Paul" if i == 7 else None, terrain="trail" if i % 3 == 0 else "road",
                 avg_hr=140 + i % 10 if i != 5 else None, hrss=50 + i, source="garmin")
        out.append(a)
    return out


def test_activity_list_pagination_and_filters():
    acts = _list_acts()
    first = stats.activity_list(acts)
    assert first["total"] == 60 and first["pages"] == 2 and len(first["rows"]) == 50   # 50 par défaut
    assert (first["first"], first["last"]) == (1, 50)
    assert first["rows"][0]["date"] > first["rows"][1]["date"]           # récentes d'abord
    small = stats.activity_list(acts, per_page=25, page=99)
    assert small["page"] == 3 and len(small["rows"]) == 10                # page bornée
    assert (small["first"], small["last"]) == (51, 60)
    assert stats.activity_list(acts, per_page=33)["per_page"] == 50       # taille inconnue : défaut
    assert stats.activity_list(acts, terrain="trail")["total"] == 20
    assert stats.activity_list(acts, year=2024)["total"] == 0
    found = stats.activity_list(acts, query="paul")
    assert found["total"] == 1 and found["rows"][0]["name"] == "Sortie 7"


def test_activity_list_distance_and_gain_ranges():
    acts = _list_acts()                    # distances de 5 à 11 km, D+ de 0 à 590 m
    assert stats.activity_list(acts, distance=(10, None))["total"] == 16
    assert stats.activity_list(acts, distance=(None, 5))["total"] == 9
    assert stats.activity_list(acts, distance=(6, 7), gain=(100, 300))["total"] == 6
    assert stats.activity_list(acts, gain=(1000, None))["total"] == 0
    empty = stats.activity_list(acts, gain=(1000, None))
    assert (empty["first"], empty["last"]) == (0, 0)
    assert stats.list_bounds(acts) == {"distance_km": 11, "gain_m": 590}
    assert stats.list_bounds([]) == {"distance_km": 1, "gain_m": 10}


def test_activity_list_sort_and_missing_values_last():
    acts = _list_acts()
    rows = stats.activity_list(acts, sort="distance", order="desc")["rows"]
    assert rows[0]["distance_km"] == 11
    hr = stats.activity_list(acts, sort="hr", order="asc", page=2)["rows"]
    assert hr[-1]["avg_hr"] is None                                       # sans FC : en dernier
    hr_desc = stats.activity_list(acts, sort="hr", order="desc", page=2)["rows"]
    assert hr_desc[-1]["avg_hr"] is None
    pace = stats.activity_list(acts, sort="pace", order="asc")["rows"]
    assert pace[0]["pace_s_km"] <= pace[1]["pace_s_km"]                   # les plus rapides d'abord
    assert stats.activity_list(acts, sort="nimporte")["rows"][0]["date"].startswith("2025-12")


# ---------- performance ----------

def eff(kind, key, value, year, terrain="road", extra=None, name="x"):
    return {"kind": kind, "key": key, "value": value, "extra": extra, "id": 1, "year": year,
            "date": f"{year}-05-01", "name": name, "terrain": terrain}


def test_performance():
    efforts = [eff("distance", 5000, 1300, 2025), eff("distance", 5000, 1250, 2026, name="record"),
               eff("distance", 5000, 1200, 2026, terrain="trail"),
               eff("duration", 1200, 4500, 2025), eff("duration", 1200, 4800, 2026),
               eff("climb", 0, 900, 2025, terrain="trail", extra=250), eff("climb", 0, 800, 2026, extra=300)]
    p = stats.performance(efforts, "road")
    five = [r for r in p["records"] if r["key"] == 5000][0]
    assert [e["time_s"] for e in five["top"]] == [1250, 1300]      # le trail est à part
    assert five["top"][0]["pace_s_km"] == 250 and five["top"][0]["name"] == "record"
    assert p["by_year"][0]["year"] == 2026 and p["by_year"][0]["times"]["5000"] == 1250
    assert p["by_year"][0]["times"]["10000"] is None
    assert p["curve"]["2026"][2] == pytest.approx(250)              # 1200 s pour 4,8 km
    assert [v["vam"] for v in p["vam_by_year"]] == [900, 800]       # VAM : route et trail confondus
    assert stats.performance(efforts, "road", year=2025)["records"][2]["top"][0]["time_s"] == 1300
    assert stats.performance(efforts, "trail")["records"][2]["top"][0]["time_s"] == 1200


# ---------- forme ----------

def test_banister_one_hour_at_lthr_every_day_converges_to_100():
    start = date(2026, 1, 1)
    daily = {start + timedelta(days=i): 100.0 for i in range(400)}
    s = stats.banister(daily, start, start + timedelta(days=399))
    assert s[-1]["fitness"] == pytest.approx(100, abs=0.1)
    assert s[-1]["fatigue"] == pytest.approx(100, abs=0.01)
    assert s[0]["form"] == 0 and s[1]["form"] < 0           # la fatigue monte plus vite que la fitness


def test_form_zones():
    assert stats.form_zone(30)[0] == "transition"
    assert stats.form_zone(10)[0] == "fresh"
    assert stats.form_zone(0)[0] == "neutral"
    assert stats.form_zone(-20)[0] == "optimal"
    assert stats.form_zone(-40)[0] == "overload"


def test_forme_payload():
    acts = []
    for i in range(60):
        a = act((date(2026, 9, 1) + timedelta(days=i)).isoformat(), 10, gain=20, moving=3600)
        a.update(hrss=80.0, terrain="road", avg_hr=140, ef=1.4 + i / 1000, decoupling_pct=3.0 + i / 100,
                 zone1_s=1000, zone2_s=2000, zone3_s=500, zone4_s=100, zone5_s=0)
        acts.append(a)
    acts[0]["avg_hr"] = 165                                   # pas une sortie facile
    f = stats.forme(acts, date(2026, 11, 3), lthr=170)
    assert f["today"]["fitness"] > 0 and f["today"]["zone"] in ("neutral", "fresh")
    assert len(f["ef_points"]) == 59
    assert [m["month"] for m in f["ef_monthly"]] == ["2026-09", "2026-10"]
    gap = stats.forme([acts[1], dict(acts[2], start=datetime(2026, 12, 5, 12))], date(2026, 12, 31), 170)
    assert [m["ef"] is None for m in gap["ef_monthly"]] == [False, True, True, False]   # sept. -> déc.
    assert len(f["decoupling"]) == 60
    assert f["zones"][0]["year"] == 2026 and sum(f["zones"][0]["pct"]) == pytest.approx(100, abs=0.2)
    assert f["peaks"][-1]["year"] == 2026
    assert len(f["series"]["dates"]) == len(f["series"]["fitness"]) == 64


def test_route_comparison():
    acts = [dict(act(f"2026-01-0{i + 1}", 10, moving=m), id=i, route_id=7)
            for i, m in enumerate((3000, 3300, 3600))]
    acts.append(dict(act("2026-01-09", 10, moving=2000), id=9, route_id=9))   # parcours couru une fois
    cmp = stats.route_comparison(acts)
    assert set(cmp) == {0, 1, 2}
    assert cmp[0] == {"route_id": 7, "n": 3, "mean_others_s": 3450, "diff_s": -450, "diff_pct": -13.0,
                      "rank": 1, "best_s": 3000}
    assert cmp[2]["rank"] == 3 and cmp[2]["diff_s"] == 450


def test_form_context():
    start = date(2025, 1, 1)
    days = [start + timedelta(days=i) for i in range(500)]
    daily = {d: (150.0 if d.month in (5, 6) else 40.0) for d in days}      # bloc de charge en mai-juin
    series = stats.banister(daily, days[0], days[-1])
    ctx = stats.form_context(series, days[-1])
    f = ctx["fitness"]
    assert f["max_date"].startswith("2025-06") or f["max_date"].startswith("2025-07")
    assert f["min"] <= f["p25_12m"] <= f["mean_12m"] <= f["max"]
    assert f["year_ago"] is not None and 0 <= f["rank_pct"] <= 100
    assert ctx["form"]["min"] < 0 < ctx["form"]["max"]


def test_linear_trend():
    pts = [((date(2025, 1, 1) + timedelta(days=30 * i)).isoformat(), 1.0 + 0.01 * i) for i in range(13)]
    tr = stats.linear_trend(pts)
    assert tr["per_year"] == pytest.approx(0.01 * 365.25 / 30, rel=0.01)
    assert tr["start"][1] == pytest.approx(1.0) and tr["end"][1] == pytest.approx(1.12)
    assert stats.linear_trend(pts[:3]) is None                                  # trop peu de points
    assert stats.linear_trend(pts, since=date(2025, 6, 1))["n"] == 7         # 30 juin -> 27 déc.


def test_year_outlook():
    o = stats.year_outlook(ACTS, date(2026, 11, 3))
    assert o["distance_km"]["record"] == 30 and o["distance_km"]["record_year"] == 2025
    assert o["distance_km"]["projection"] == round(35 / 307 * 365)
    assert o["per_week"] == round(3 / (307 / 7), 1)
    assert stats.year_outlook(ACTS, date(2026, 1, 5))["distance_km"]["projection"] is None   # trop tôt


def test_effort_ranks():
    from app.detail import effort_ranks

    efforts = [
        {"kind": "distance", "key": 5000, "value": v, "id": i, "year": y, "terrain": t}
        for i, (v, y, t) in enumerate([(1300, 2025, "road"), (1250, 2026, "road"), (1280, 2026, "road"),
                                       (1200, 2026, "trail"), (1350, 2026, "road")])
    ]
    r = effort_ranks(efforts, 2, "distance", 5000, "road", 2026)
    assert r["in_year"] == {"rank": 2, "of": 3}
    assert r["all_time"] == {"rank": 2, "of": 4}                    # le trail est classé à part
    climbs = [{"kind": "climb", "key": 0, "value": v, "id": i, "year": 2026, "terrain": t}
              for i, (v, t) in enumerate([(900, "trail"), (950, "road")])]
    assert effort_ranks(climbs, 0, "climb", 0, "trail", 2026, higher_is_better=True)["all_time"]["rank"] == 2
    assert effort_ranks(efforts, 99, "distance", 5000, "road", 2026) is None


def test_ef_reference():
    acts = []
    for i in range(8):
        a = act(f"2026-0{1 + i // 4}-{10 + i:02d}", 10)
        a.update(id=i, terrain="road", ef=1.0 + i * 0.02)
        acts.append(a)
    trail = dict(act("2026-03-01", 10), id=50, terrain="trail", ef=0.8)
    old = dict(act("2024-01-01", 10), id=51, terrain="road", ef=2.0)          # plus d'un an avant : ignorée
    current = dict(act("2026-04-01", 10), id=99, terrain="road", ef=1.12)
    ref = stats.ef_reference(acts + [trail, old, current], current)
    assert ref == {"median": 1.07, "n": 8, "diff_pct": 4.7}
    assert stats.ef_reference(acts[:4] + [current], current) is None        # moins de 5 sorties
    assert stats.ef_reference(acts, dict(current, ef=None)) is None
    later = dict(act("2026-01-01", 10), id=98, terrain="road", ef=1.0)      # pas de sortie antérieure
    assert stats.ef_reference(acts, later) is None


def test_decoupling_applies_only_on_flat_road():
    flat = dict(act("2026-01-01", 15, gain=60), terrain="road", decoupling_pct=3.0)
    assert stats.decoupling_applies(flat)
    assert not stats.decoupling_applies(dict(flat, gain_m=200))             # route vallonnée
    assert not stats.decoupling_applies(dict(flat, terrain="trail"))
    assert not stats.decoupling_applies(dict(flat, decoupling_pct=None))
