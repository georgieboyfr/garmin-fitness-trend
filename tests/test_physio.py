from datetime import date

import pytest

from app import physio

DAY = date(2026, 11, 3)


def effort(kind, key, value, day="2026-10-20", terrain="road", id_=1):
    return {"kind": kind, "key": key, "value": value, "date": day, "terrain": terrain, "id": id_,
            "name": "Sortie"}


def test_vma_is_best_five_minute_road_speed_and_vo2max_follows():
    efforts = [effort("duration", 300, 1350.0), effort("duration", 300, 1500.0, id_=2),
               effort("duration", 300, 1700.0, terrain="trail", id_=3),        # trail ignoré
               effort("duration", 300, 1800.0, day="2025-01-01", id_=4)]        # trop ancien
    v = physio.vma(efforts, DAY)
    assert v["kmh"] == 18.0 and v["activity_id"] == 2 and not v["fallback"]
    assert v["vo2max"] == pytest.approx(63.0) and v["pace_s_km"] == 200.0
    old = physio.vma([effort("duration", 300, 1400.0, day="2026-06-01")], DAY)
    assert old["fallback"] and physio.vma([], DAY) is None


def test_threshold_pace_is_one_hour_distance_from_riegel():
    v = physio.threshold_pace([effort("distance", 10000, 2400.0)], DAY)
    expected = 10000 * (3600 / 2400) ** (1 / 1.06)
    assert v["distance_m"] == round(expected) and v["reference"]["label"] == "10 km"
    assert v["pace_s_km"] == pytest.approx(3600 / expected * 1000, abs=0.1)
    assert physio.threshold_pace([], DAY) is None


def test_threshold_hr_as_share_of_max():
    est = {"best_60min": {"hr": 166, "date": "2026-03-29", "activity_id": 9}}
    h = physio.threshold_hr(est, 188)
    assert h["hr"] == 166 and h["pct_max"] == 88
    assert physio.threshold_hr({"best_60min": None}, 188) is None
    assert physio.threshold_hr(est, None)["pct_max"] is None
