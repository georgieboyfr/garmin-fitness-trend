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
    assert len(h["cumulative"]["current"]) == 307            # 1er janv. -> 3 nov.
    assert len(h["cumulative"]["previous"]) == 365
    assert h["cumulative"]["previous"][-1] == 30
    assert h["week"]["count"] == 1                           # lundi 2 nov. -> mardi 3 nov.
    assert stats.home([], date(2026, 11, 3))["last"] is None
