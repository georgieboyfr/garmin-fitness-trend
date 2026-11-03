from datetime import date, datetime

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
    assert first["total"] == 60 and first["pages"] == 3 and len(first["rows"]) == 25
    assert first["rows"][0]["date"] > first["rows"][1]["date"]           # récentes d'abord
    assert stats.activity_list(acts, page=99)["page"] == 3                # page bornée
    assert len(stats.activity_list(acts, page=3)["rows"]) == 10
    assert stats.activity_list(acts, terrain="trail")["total"] == 20
    assert stats.activity_list(acts, year=2024)["total"] == 0
    found = stats.activity_list(acts, query="paul")
    assert found["total"] == 1 and found["rows"][0]["name"] == "Sortie 7"


def test_activity_list_sort_and_missing_values_last():
    acts = _list_acts()
    rows = stats.activity_list(acts, sort="distance", order="desc")["rows"]
    assert rows[0]["distance_km"] == 11
    hr = stats.activity_list(acts, sort="hr", order="asc", page=3)["rows"]
    assert hr[-1]["avg_hr"] is None                                       # sans FC : en dernier
    hr_desc = stats.activity_list(acts, sort="hr", order="desc", page=3)["rows"]
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
