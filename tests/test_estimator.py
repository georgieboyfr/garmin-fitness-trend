import json
import math
from datetime import date, datetime

import pytest

from app import estimator

DAY = date(2026, 11, 3)


def eff(kind, key, value, day, terrain="road", extra=None, id=1, name="x"):
    return {"kind": kind, "key": key, "value": value, "extra": extra, "id": id, "name": name,
            "date": day, "year": int(day[:4]), "terrain": terrain, "avg_hr": None}


def act(day, km=10.0, terrain="road", hrss=50.0, ef=None, avg_hr=140, gain=0.0, bins=None, moving=3600):
    return {"start": datetime.fromisoformat(day + "T09:00:00"), "distance_km": km, "terrain": terrain,
            "hrss": hrss, "ef": ef, "avg_hr": avg_hr, "gain_m": gain, "moving_duration_s": moving,
            "grade_bins": json.dumps(bins) if bins else None}


# ---------- forme actuelle ----------

def test_pace_curve_keeps_best_of_each_effort_per_terrain():
    efforts = [eff("duration", 1200, 4000, "2026-10-01"), eff("duration", 1200, 4200, "2026-10-10", id=2),
               eff("distance", 5000, 1500, "2026-10-01"), eff("distance", 5000, 1450, "2026-10-12", id=3),
               eff("distance", 5000, 1300, "2026-10-12", terrain="trail")]
    curve = estimator.pace_curve(efforts, "road")
    assert curve["durations"] == [{"key": 1200, "label": "20 min", "distance_m": 4200, "pace_s_km": 285.7,
                                   "date": "2026-10-10", "activity_id": 2, "name": "x"}]
    assert curve["distances"][0]["time_s"] == 1450 and curve["distances"][0]["pace_s_km"] == 290


def test_slope_paces_aggregates_bins_into_bands():
    bins = [[0, 600, 1800], [-2, 300, 900],               # plat : 900 s pour 2 700 m
            [-8, 200, 700], [-6, 200, 700],               # descente douce
            [-14, 100, 300]]                              # descente : moins de 5 min
    out = {r["low"]: r for r in estimator.slope_paces([act("2026-10-01", bins=bins)])}
    assert out[-2]["pace_s_km"] == pytest.approx(333.3, abs=0.1) and out[-2]["vertical_mh"] is None
    assert out[-10]["pace_s_km"] == pytest.approx(285.7, abs=0.1)
    assert out[-10]["vertical_mh"] == round((700 * 0.07 + 700 * 0.05) / 400 * 3600)
    assert out[-20]["seconds"] == 100 and out[-20]["pace_s_km"] is None


def test_current_form_uses_only_the_12_weeks_before_the_evening_of_the_day():
    acts = [act("2026-05-01", km=30), act("2026-08-12", km=8), act("2026-11-03", km=12),
            act("2026-11-04", km=50)]
    efforts = [eff("distance", 10000, 2900, "2026-05-01"), eff("distance", 10000, 3100, "2026-09-01"),
               eff("climb", 0, 900, "2026-10-01", terrain="trail", extra=400)]
    p = estimator.current_form(acts, efforts, DAY, lthr=170)
    assert p["version"] == estimator.PROFILE_VERSION
    assert p["start"] == "2026-08-12" and p["runs"] == 2 and p["distance_km"] == 20
    assert p["road"]["distances"][0]["time_s"] == 3100
    assert p["climbs"][0]["vam"] == 900 and p["climbs"][0]["time_s"] == 1600
    assert p["load"]["fitness"] > 0


def test_current_form_ef_compared_with_previous_year():
    acts = [act(f"2026-0{m}-15", ef=1.50) for m in range(1, 8)] + [act("2026-10-01", ef=1.65)]
    ef = estimator.current_form(acts, [], DAY, lthr=170)["ef"]
    assert ef == {"value": 1.65, "n": 1, "reference": 1.5, "delta_pct": 10.0}


def test_current_form_empty_history():
    p = estimator.current_form([], [], DAY, lthr=170)
    assert p["runs"] == 0 and p["load"] is None and p["ef"] is None and p["climbs"] == []


# ---------- route : Riegel ----------

def riegel_efforts(k=1.10, base_day="2026-10-01", old_day="2025-06-01"):
    """Frontière parfaite d'exposant k : 5 km en 25 min."""
    def t(d):
        return 1500 * (d / 5000) ** k
    return [eff("distance", 5000, t(5000), base_day), eff("distance", 10000, t(10000), old_day, id=2),
            eff("distance", 21097.5, t(21097.5), old_day, id=3), eff("distance", 1000, 200, base_day)]


def test_personal_exponent_fits_the_frontier():
    x = estimator.personal_exponent(riegel_efforts(1.10), DAY)
    assert x["personal"] and x["value"] == pytest.approx(1.10, abs=0.001) and x["n"] == 3
    assert x["range_km"] == [5.0, 21.1]


def test_personal_exponent_bounded_and_default():
    assert estimator.personal_exponent(riegel_efforts(1.40), DAY)["value"] == estimator.EXPONENT_BOUNDS[1]
    assert estimator.personal_exponent(riegel_efforts(1.40), DAY)["bounded"]
    few = [eff("distance", 5000, 1500, "2026-10-01"), eff("distance", 10000, 3100, "2026-10-01")]
    x = estimator.personal_exponent(few, DAY)     # rapport de distances insuffisant
    assert not x["personal"] and x["value"] == estimator.RIEGEL_DEFAULT


def test_road_points_ignore_short_efforts_trail_and_other_dates():
    efforts = riegel_efforts() + [eff("duration", 300, 1500, "2026-10-01"),
                                  eff("duration", 1200, 4000, "2026-10-01"),
                                  eff("distance", 10000, 2000, "2026-10-01", terrain="trail")]
    pts = estimator.road_points(efforts, date(2026, 8, 12), DAY)
    assert [(p["kind"], p["distance_m"]) for p in pts] == [("duration", 4000), ("distance", 5000)]


def test_predict_road_extrapolates_the_fastest_recent_effort():
    efforts = riegel_efforts(1.10)
    p = estimator.predict_road(efforts, DAY, 10000)
    assert p["reference"]["distance_m"] == 5000            # seul effort route des 12 semaines
    assert p["exponent"] == estimator.STANDARD_EXPONENT
    assert p["realistic_s"] == round(1500 * 2 ** 1.06)
    spread = estimator.BASE_SPREAD + estimator.EXPONENT_SPREAD * math.log(2)
    assert p["optimistic_s"] == pytest.approx(p["realistic_s"] * math.exp(-spread), abs=1)
    assert p["prudent_s"] == pytest.approx(p["realistic_s"] * math.exp(spread), abs=1)
    assert p["realistic_pace_s_km"] == pytest.approx(p["realistic_s"] / 10, abs=0.1)
    assert not p["fallback"]


def test_predict_road_takes_the_best_of_several_references():
    efforts = riegel_efforts(1.10) + [eff("distance", 10000, 3000, "2026-10-20", id=9)]   # 10 km rapide
    p = estimator.predict_road(efforts, DAY, 21097.5)
    assert p["reference"]["activity_id"] == 9
    assert p["realistic_s"] == round(3000 * 2.10975 ** p["exponent"]["value"])


def test_predict_road_gain_adds_flat_equivalent_distance():
    efforts = riegel_efforts(1.10)
    flat = estimator.predict_road(efforts, DAY, 10000)
    hilly = estimator.predict_road(efforts, DAY, 10000, gain_m=100)
    assert estimator.CLIMB_EQUIVALENT == pytest.approx(6.0, abs=0.2)
    assert hilly["equivalent_m"] == round(10000 + 100 * estimator.CLIMB_EQUIVALENT)
    assert hilly["realistic_s"] > flat["realistic_s"]


def test_predict_road_falls_back_to_six_months_then_none():
    efforts = [eff("distance", 5000, 1500, "2026-07-01")]
    p = estimator.predict_road(efforts, DAY, 10000)
    assert p["fallback"] and p["window_days"] == estimator.FALLBACK_WINDOW_DAYS
    assert estimator.predict_road([eff("distance", 5000, 1500, "2026-01-01")], DAY, 10000) is None
    assert estimator.predict_road(efforts, DAY, 0) is None


def test_road_table_standard_distances():
    rows = estimator.road_table(riegel_efforts(1.10), DAY)
    assert [r["label"] for r in rows] == ["5 km", "10 km", "Semi", "Marathon"]
    assert rows[0]["realistic_s"] == 1500
    assert all(a["realistic_s"] < b["realistic_s"] for a, b in zip(rows, rows[1:], strict=False))


# ---------- validation ----------

def race(id, day, km, elapsed, terrain="road", gain=0.0):
    a = act(day, km=km, terrain=terrain, gain=gain)
    return {**a, "id": id, "name": f"Course {id}", "distance_m": km * 1000, "elapsed_s": elapsed,
            "duration_s": elapsed}


def test_validate_road_replays_with_the_form_of_the_day_before():
    efforts = riegel_efforts(1.10, base_day="2026-09-01", old_day="2025-06-01")
    efforts.append(eff("distance", 10000, 2500, "2026-10-01", id=99))       # la course elle-même : ignorée
    acts = [race(99, "2026-10-01", 10, 3000), race(98, "2026-10-01", 10, 3000, terrain="trail"),
            race(97, "2026-09-15", 10, 3000)]
    v = estimator.validate_road(acts, efforts, {99, 98})
    assert [r["activity_id"] for r in v["races"]] == [99]
    r = v["races"][0]
    assert r["estimate"]["reference"]["distance_m"] == 5000
    assert r["estimate"]["realistic_s"] == round(1500 * 2 ** 1.06)
    assert r["error_pct"] == round((round(1500 * 2 ** 1.06) / 3000 - 1) * 100, 1)
    assert r["personal_k"] == pytest.approx(1.10, abs=0.001)
    assert r["personal_s"] == pytest.approx(1500 * 2 ** 1.10, abs=2)
    assert v["used"]["n"] == 1 and v["used"]["mae_pct"] == abs(r["error_pct"])
    assert v["used"]["within"] == int(r["within"])


def test_validate_road_summary_and_missing_estimate():
    efforts = riegel_efforts(1.10, base_day="2026-09-01")
    acts = [race(1, "2026-10-01", 10, 3000), race(2, "2026-10-02", 10, 3400), race(3, "2020-01-01", 10, 3000)]
    v = estimator.validate_road(acts, efforts, {1, 2, 3})
    errors = [r["error_pct"] for r in v["races"] if r["error_pct"] is not None]
    assert len(errors) == 2 and v["races"][-1]["estimate"] is None
    assert v["used"]["bias_pct"] == round(sum(errors) / 2, 1)
    assert v["used"]["mae_pct"] == round(sum(abs(e) for e in errors) / 2, 1)
    assert estimator.validate_road([], efforts, set()) == {"version": estimator.ESTIMATE_VERSION, "races": [],
                                                           "used": None, "personal": None}


# ---------- modèle allure-pente ----------

def hilly(day, flat_speed, factors, terrain="trail"):
    """Sortie avec 10 min de plat à flat_speed et 5 min dans chaque tranche, au facteur donné."""
    bins = [[0, 600, 600 * flat_speed]]
    bins += [[low, 300, 300 * flat_speed / f] for low, f in factors.items()]
    return act(day, terrain=terrain, bins=bins)


def test_grade_pace_model_is_independent_of_run_intensity():
    factors = {-20: 1.25, -10: 0.95, 10: 1.4, 20: 2.0}
    acts = [hilly("2026-06-01", 2.5, factors), hilly("2026-07-01", 3.5, factors),
            hilly("2026-08-01", 3.0, factors)]
    m = estimator.grade_pace_model(acts, DAY)
    assert m["version"] == estimator.MODEL_VERSION and m["activities"] == 3
    by = {b["grade"]: b for b in m["bins"]}
    assert set(by) == {-19, -9, 1, 11, 21}
    assert by[11]["raw"] == pytest.approx(1.4, abs=0.001) and by[-19]["raw"] == pytest.approx(1.25, abs=0.001)
    assert by[1]["raw"] == pytest.approx(1.0) and by[11]["activities"] == 3
    assert by[21]["minetti"] == pytest.approx(float(estimator.grade.minetti_cost(0.21)) / 3.6, abs=0.001)


def test_grade_pace_model_smooths_neighbours_and_needs_three_runs():
    acts = [hilly(f"2026-0{m}-01", 3.0, {10: 1.3, 12: 1.5}) for m in (6, 7, 8)]
    acts.append(hilly("2026-09-01", 3.0, {30: 3.0}))                    # une seule sortie : ignorée
    by = {b["grade"]: b for b in estimator.grade_pace_model(acts, DAY)["bins"]}
    assert 31 not in by
    assert by[11]["factor"] == pytest.approx(math.exp((math.log(1.3) + math.log(1.5)) / 2), abs=0.001)


def test_grade_pace_model_window_and_flat_reference():
    old = [hilly("2025-01-01", 3.0, {10: 1.3}) for _ in range(3)]
    no_flat = [act("2026-10-01", bins=[[10, 600, 1200]]) for _ in range(3)]
    assert estimator.grade_pace_model(old + no_flat, DAY) is None
    assert estimator.grade_pace_model([], DAY) is None


def test_grade_factor_interpolates_and_holds_edges():
    model = {"bins": [{"grade": -9, "factor": 0.9}, {"grade": 1, "factor": 1.0},
                      {"grade": 11, "factor": 1.4}]}
    assert estimator.grade_factor(model, 6) == pytest.approx(1.2)
    assert estimator.grade_factor(model, -30) == 0.9 and estimator.grade_factor(model, 40) == 1.4


def test_model_table_paces_from_flat_pace():
    model = {"flat_pace_s_km": 300.0,
             "bins": [{"grade": g, "factor": 1 + g / 50} for g in range(-29, 32, 2)]}
    rows = {r["grade"]: r for r in estimator.model_table(model)}
    assert rows[0]["vertical_mh"] is None
    assert rows[10]["pace_s_km"] == pytest.approx(300 * estimator.grade_factor(model, 10), abs=0.1)
    assert rows[10]["vertical_mh"] == round(100 / rows[10]["pace_s_km"] * 3600)


# ---------- périodes réglables ----------

def test_form_window_is_configurable():
    acts = [act("2026-08-12", km=8), act("2026-10-01", km=12)]
    efforts = [eff("distance", 5000, 1500, "2026-08-20"), eff("distance", 5000, 1600, "2026-10-01")]
    p = estimator.current_form(acts, efforts, DAY, lthr=170, window_days=42)
    assert p["window_days"] == 42 and p["start"] == "2026-09-23" and p["runs"] == 1
    assert p["road"]["distances"][0]["time_s"] == 1600
    assert estimator.predict_road(efforts, DAY, 5000, window_days=42)["reference"]["time_s"] == 1600
    assert estimator.predict_road(efforts, DAY, 5000)["reference"]["time_s"] == 1500
    assert estimator.road_table(efforts, DAY, 42)[0]["window_days"] == 42


def test_grade_pace_model_period_and_whole_history():
    factors = {10: 1.4}
    acts = [hilly(day, 3.0, factors) for day in ("2023-05-01", "2024-05-01", "2025-05-01", "2026-09-01")]
    assert estimator.grade_pace_model(acts, DAY, 182) is None                  # une seule sortie
    m = estimator.grade_pace_model(acts, DAY, None)
    assert m["activities"] == 4 and m["start"] == "2023-05-01"
    assert estimator.grade_pace_model(acts, DAY, 730) is None                  # deux sorties seulement
    assert estimator.grade_pace_model(acts, DAY, 1100)["activities"] == 3
