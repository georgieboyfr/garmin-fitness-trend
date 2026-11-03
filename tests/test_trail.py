import json
import math
from datetime import date, datetime

import numpy as np
import pytest

from app import estimator, trail
from app.track_parser import parse_route, parse_waypoints

DAY = date(2026, 11, 3)
FLAT_MODEL = {"bins": [{"grade": -41, "factor": 1.0}, {"grade": 41, "factor": 1.0}]}
SLOPE_MODEL = {"bins": [{"grade": -21, "factor": 1.2}, {"grade": -1, "factor": 1.0},
                        {"grade": 1, "factor": 1.0}, {"grade": 21, "factor": 2.0}]}


def gpx(points, ele=True, kind="trkpt"):
    body = "".join(f'<{kind} lat="{lat}" lon="{lon}">' + (f"<ele>{e}</ele>" if ele else "") + f"</{kind}>"
                   for lat, lon, e in points)
    return f'<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}' \
           '</trkseg></trk></gpx>'.encode()


def line(km, alt=lambda d: 0.0, step_m=20):
    """Trace vers le nord (1° de latitude ≈ 111,2 km), altitude fonction de la distance."""
    n = int(km * 1000 / step_m)
    return [(45 + i * step_m / 111195, 5.0, alt(i * step_m)) for i in range(n + 1)]


def eff(kind, key, value, day):
    return {"kind": kind, "key": key, "value": value, "extra": None, "id": 1, "name": "x", "date": day,
            "year": int(day[:4]), "terrain": "road", "avg_hr": None}


def test_parse_route_reads_tracks_and_routes_without_time():
    pts = line(1)
    lats, lons, eles = parse_route(gpx(pts))
    assert len(lats) == len(pts) and eles[0] == 0.0
    lats, _, eles = parse_route(gpx(pts, ele=False, kind="rtept"))
    assert len(lats) == len(pts) and eles[0] is None


def test_route_profile_requires_distance_and_elevation():
    lats, lons, eles = parse_route(gpx(line(5, lambda d: d * 0.1)))
    p = trail.route_profile(lats, lons, eles)
    assert p["distance"][-1] == pytest.approx(5000, abs=15) and p["altitude"][-1] == pytest.approx(500, abs=5)
    assert trail.route_profile(*parse_route(gpx(line(0.5)))) is None
    assert trail.route_profile(*parse_route(gpx(line(5), ele=False))) is None


def test_equivalent_steps_apply_the_grade_model():
    d = np.arange(0, 2001, 10.0)
    flat = {"distance": d, "altitude": np.zeros(d.size)}
    up = {"distance": d, "altitude": d * 0.21}
    assert trail.equivalent_steps(flat, SLOPE_MODEL)[-1] == pytest.approx(2000)
    assert trail.equivalent_steps(up, SLOPE_MODEL)[-1] == pytest.approx(4000, rel=0.02)


def test_total_time_riegel_then_fatigue_after_two_hours():
    ref = {"distance_m": 10000.0, "time_s": 3000.0}
    t, d0 = trail.total_time(ref, 20000, 1.3)
    assert d0 is None and t == pytest.approx(3000 * 2 ** 1.06)
    t, d0 = trail.total_time(ref, 60000, 1.3)
    assert d0 == pytest.approx(10000 * 2.4 ** (1 / 1.06))
    assert t == pytest.approx(7200 * (60000 / d0) ** 1.3)
    assert t > 3000 * 6 ** 1.06                                     # plus lent que Riegel seul


def test_passage_times_even_then_progressive_slowdown():
    x = np.linspace(0, 50000, 501)
    short = trail.passage_times(x, 6000, 1.3)
    assert short[-1] == pytest.approx(6000) and short[250] == pytest.approx(3000)
    long_ = trail.passage_times(x, 20000, 1.3)
    assert long_[-1] == pytest.approx(20000, rel=1e-6)
    pace = np.diff(long_)
    assert np.all(np.diff(pace) >= -1e-6)                          # l'allure ne fait que ralentir
    first = pace[long_[1:] < 7200]
    assert first.max() == pytest.approx(first.min(), rel=1e-6)     # régulière pendant 2 h
    assert pace[-1] > pace[0] * 1.2


def test_segments_split_climbs_and_descents():
    d = np.arange(0, 6001, 10.0)
    alt = np.where(d <= 2000, d * 0.1, np.where(d <= 4000, 200 - (d - 2000) * 0.1, 0.0))
    times = d / 3.0
    segs = trail.segments({"distance": d, "altitude": alt}, times)
    assert [s["kind"] for s in segs] == ["up", "down", "flat"]
    assert [s["label"] for s in segs] == ["Montée", "Descente", "Plat"]
    assert segs[0]["gain_m"] == 200 and segs[1]["loss_m"] == 200 and segs[0]["end_km"] == 2.0
    assert segs[-1]["passage_s"] == 2000 and segs[0]["time_s"] == round(2000 / 3)


def test_segments_separate_a_gentle_and_a_steep_climb():
    d = np.arange(0, 4001, 10.0)
    alt = np.where(d <= 2000, d * 0.02, 40 + (d - 2000) * 0.2)          # +2 % puis +20 %
    segs = trail.segments({"distance": d, "altitude": alt}, d / 3.0)
    assert [(s["label"], s["end_km"]) for s in segs] == [("Plat", 2.0), ("Forte montée", 4.0)]
    assert segs[1]["grade_pct"] == pytest.approx(20, abs=0.5)


def test_segments_rolling_terrain():
    d = np.arange(0, 4001, 10.0)
    bumps = 15 * np.sin(d / 1000 * 2 * np.pi * 3)                        # 3 bosses de 30 m sur 4 km
    segs = trail.segments({"distance": d, "altitude": bumps, "threshold_m": 3.5}, d / 3.0)
    assert [s["label"] for s in segs] == ["Vallonné"] and segs[0]["gain_m"] >= 60
    small = 3 * np.sin(d / 100)                                         # ondulations de 6 m : plat
    assert [s["label"] for s in trail.segments({"distance": d, "altitude": small, "threshold_m": 3.5},
                                               d / 3.0)] == ["Plat"]


def test_fit_segments_finds_slope_changes():
    d = np.arange(0, 3001, 50.0)
    a = np.where(d <= 1000, 0.0, np.where(d <= 2000, (d - 1000) * 0.15, 150.0))
    assert trail.fit_segments(d, a) == [0, 20, 40, 60]
    assert trail.fit_segments(d[:3], a[:3]) == [0, 2]


def test_fatigue_exponent_from_long_runs_or_default():
    def act(day, km, hours):
        bins = [[0, hours * 3600, km * 1000]]
        return {"id": 1, "name": "x", "start": datetime.fromisoformat(day + "T08:00:00"), "terrain": "trail",
                "grade_bins": json.dumps(bins)}
    acts = [act("2025-05-01", 20, 2.2), act("2025-06-01", 30, 3.5), act("2025-07-01", 50, 6.5),
            act("2026-12-01", 80, 12)]                               # après le jour : ignorée
    f = trail.fatigue_exponent(acts, FLAT_MODEL, DAY)
    xs, ys = [math.log(m) for m in (20e3, 30e3, 50e3)], [math.log(h * 3600) for h in (2.2, 3.5, 6.5)]
    mx, my = sum(xs) / 3, sum(ys) / 3
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)
    assert f["personal"] and f["fitted"] == round(k, 3) and len(f["points"]) == 3
    assert not trail.fatigue_exponent(acts[:2], FLAT_MODEL, DAY)["personal"]
    assert trail.fatigue_exponent(acts[:2], FLAT_MODEL, DAY)["value"] == trail.FATIGUE_DEFAULT


def test_predict_trail_end_to_end():
    lats, lons, eles = parse_route(gpx(line(12, lambda d: 300 - abs(d - 6000) * 0.05)))
    profile = trail.route_profile(lats, lons, eles)
    efforts = [eff("distance", 10000, 3000, "2026-10-01")]
    r = trail.predict_trail(profile, SLOPE_MODEL, efforts, DAY)
    assert r["version"] == trail.TRAIL_VERSION and not r["fatigue_applies"]
    assert r["equivalent_m"] > r["distance_m"]
    assert r["realistic_s"] == round(3000 * (r["equivalent_m"] / 10000) ** estimator.RIEGEL_DEFAULT)
    assert r["optimistic_s"] < r["realistic_s"] < r["prudent_s"]
    assert r["segments"][-1]["passage_s"] == r["realistic_s"]
    assert len(r["chart"]["km"]) == len(r["chart"]["time"]) and r["chart"]["time"][-1] == r["realistic_s"]
    assert trail.predict_trail(profile, None, efforts, DAY) is None
    assert trail.predict_trail(profile, SLOPE_MODEL, [], DAY) is None


def test_estimate_gpx_errors():
    lats, lons, eles = parse_route(gpx(line(5)))
    assert "error" in trail.estimate_gpx(lats, lons, [None] * len(eles), [], [], DAY)
    assert "error" in trail.estimate_gpx(lats, lons, eles, [], [], DAY)       # pas de modèle


class FakeDem:
    def __init__(self, alt=lambda lat: (lat - 45) * 111195 * 0.1, fail=False, holes=0.0):
        self.alt, self.fail, self.holes = alt, fail, holes

    def elevations(self, lats, lons):
        if self.fail:
            raise RuntimeError("MNT injoignable")
        z = self.alt(np.asarray(lats))
        z[: int(len(z) * self.holes)] = np.nan
        return z, "ign"


def test_dem_altitudes_replace_noisy_gpx_elevation():
    rng = np.random.default_rng(1)
    pts = [(la, lo, 0.0 + rng.normal(0, 4)) for la, lo, _ in line(5)]       # GPX plat mais bruité
    lats, lons, eles = parse_route(gpx(pts))
    noisy = trail.route_profile(lats, lons, eles)
    raw = np.diff(eles)
    assert noisy["source"] == "gpx" and noisy["gain_m"] < raw[raw > 0].sum() / 3  # bruit filtré
    dem = trail.dem_altitudes(FakeDem(), lats, lons)
    p = trail.route_profile(lats, lons, eles, dem)
    assert p["source"] == "ign" and p["gain_m"] == pytest.approx(500, abs=10)
    assert trail.dem_altitudes(FakeDem(fail=True), lats, lons) is None
    assert trail.dem_altitudes(FakeDem(holes=0.2), lats, lons) is None      # MNT trop incomplet


def test_waypoints_become_aid_stations_near_the_track():
    pts = line(10)
    wpts = "".join(f'<wpt lat="{la}" lon="{lo}"><name>{n}</name></wpt>' for la, lo, n in [
        (45 + 4000 / 111195, 5.0005, "Ravito 1"),          # à 40 m de la trace, km 4
        (45 + 7000 / 111195, 5.0, "Col"),                  # sur la trace, km 7
        (45 + 2000 / 111195, 5.01, "Parking"),             # à 790 m : ignoré
        (45, 5.0, "Départ")])                              # au départ : ignoré
    data = gpx(pts).replace(b"<trk>", wpts.encode() + b"<trk>")
    assert parse_waypoints(data)[0] == (pytest.approx(45 + 4000 / 111195), 5.0005, "Ravito 1")
    lats, lons, _ = parse_route(data)
    st = trail.waypoint_stations(lats, lons, parse_waypoints(data))
    assert [(a["name"], a["km"], a["stop_min"]) for a in st] == [
        ("Ravito 1", pytest.approx(4.0, abs=0.03), 0.0), ("Col", pytest.approx(7.0, abs=0.03), 0.0)]
    assert trail.waypoint_stations(lats, lons, []) == []


def test_clean_stations_sorts_and_rejects_bad_input():
    st = trail.clean_stations([{"km": "8.5", "name": " Col ", "stop_min": 3},
                               {"km": 4, "name": "", "stop_min": None}])
    assert st == [{"km": 4.0, "name": "Ravito", "stop_min": 0.0}, {"km": 8.5, "name": "Col", "stop_min": 3.0}]
    for bad in ([{"km": -1}], [{"km": "x"}], [{"name": "sans km"}], [{"km": 3, "stop_min": 500}], {"km": 3},
                [3], [{"km": 1}] * (trail.AID_MAX + 1)):
        with pytest.raises(ValueError):
            trail.clean_stations(bad)


def test_predict_trail_adds_stops_after_each_aid_station():
    lats, lons, eles = parse_route(gpx(line(12, lambda d: 300 - abs(d - 6000) * 0.05)))
    profile = trail.route_profile(lats, lons, eles)
    efforts = [eff("distance", 10000, 3000, "2026-10-01")]
    base = trail.predict_trail(profile, SLOPE_MODEL, efforts, DAY)
    stations = [{"km": 6.0, "name": "Sommet", "stop_min": 5.0}, {"km": 9.0, "name": "Ferme", "stop_min": 2.0},
                {"km": 30.0, "name": "Hors parcours", "stop_min": 10.0}]
    r = trail.predict_trail(profile, SLOPE_MODEL, efforts, DAY, aid_stations=stations)
    assert r["moving_s"] == base["realistic_s"] and r["stops_s"] == 420
    assert r["realistic_s"] == base["realistic_s"] + 420
    assert r["optimistic_s"] == base["optimistic_s"] + 420 and r["prudent_s"] == base["prudent_s"] + 420
    assert r["realistic_pace_s_km"] == base["realistic_pace_s_km"]           # allure en mouvement
    sommet, ferme, finish = r["aid_stations"]
    assert [a["name"] for a in r["aid_stations"]] == ["Sommet", "Ferme", "Arrivée"] and finish["finish"]
    assert sommet["departure_s"] == sommet["arrival_s"] + 300 and sommet["leg_m"] == 6000
    assert sommet["leg_gain_m"] == pytest.approx(300, abs=5) and sommet["leg_loss_m"] == 0
    assert sommet["arrival_optimistic_s"] < sommet["arrival_s"] < sommet["arrival_prudent_s"]
    assert ferme["arrival_s"] == pytest.approx(sommet["departure_s"] + ferme["leg_s"], abs=1)
    assert finish["arrival_s"] == pytest.approx(r["realistic_s"], abs=1)
    assert sum(a["leg_s"] for a in r["aid_stations"]) == pytest.approx(r["moving_s"], abs=2)
    assert r["segments"][-1]["passage_s"] == r["realistic_s"]
    assert sum(s["time_s"] for s in r["segments"]) == pytest.approx(r["moving_s"], abs=len(r["segments"]))
    assert r["chart"]["time"][-1] == r["realistic_s"] and len(r["chart"]["aid"]) == 2
    assert [a["name"] for a in base["aid_stations"]] == ["Arrivée"]


def test_altitude_profile_uses_the_threshold_of_its_source():
    d = np.arange(0, 3001, 10.0)
    alt = 2 * np.sin(d / 40)                                            # ondulations de 4 m
    baro = trail.altitude_profile(d, alt, "barometer")
    dem = trail.altitude_profile(d, alt, "ign")
    assert baro["threshold_m"] == 1.0 and dem["threshold_m"] == 3.5
    assert baro["gain_m"] > 0 and dem["gain_m"] == 0
    assert trail.altitude_profile(d[:50], alt[:50], "barometer") is None    # moins de 1 km


def test_stop_rate_from_past_trail_races_only():
    def race(i, day, hours, stop_s, terrain="trail"):
        start = datetime.fromisoformat(day + "T08:00:00")
        return {"id": i, "name": f"c{i}", "start": start, "terrain": terrain,
                "moving_duration_s": hours * 3600, "elapsed_s": hours * 3600 + stop_s}
    acts = [race(1, "2025-05-01", 2, 72), race(2, "2025-06-01", 4, 960),
            race(3, "2025-07-01", 4, 3600, "road"),
            race(4, "2025-08-01", 4, 3600), race(5, "2027-01-01", 10, 9000)]
    r = trail.stop_rate(acts, {1, 2, 3, 5}, DAY)                 # 4 : pas une course ; 5 : après le jour
    shares = [(72 / (7200 + 72), 2), (960 / (14400 + 960), 4)]
    a = sum(s * h ** 2 for s, h in shares) / sum(h ** 4 for _, h in shares)
    assert r["personal"] and r["a"] == pytest.approx(a) and [p["activity_id"] for p in r["points"]] == [1, 2]
    assert trail.stop_rate(acts, set(), DAY) == {"a": trail.STOP_DEFAULT, "personal": False, "points": []}


def test_predict_trail_adds_history_stops_unless_aid_stops_are_entered():
    lats, lons, eles = parse_route(gpx(line(30)))
    profile = trail.route_profile(lats, lons, eles)
    efforts = [eff("distance", 10000, 3000, "2026-10-01")]
    stops = {"a": 0.01, "personal": True, "points": []}
    base = trail.predict_trail(profile, FLAT_MODEL, efforts, DAY)
    r = trail.predict_trail(profile, FLAT_MODEL, efforts, DAY, stops=stops)
    share = 0.01 * (base["moving_s"] / 3600) ** 2
    assert base["stops_source"] is None and base["stops_s"] == 0
    assert r["stops_source"] == "history" and r["stop_share_pct"] == round(share * 100, 1)
    assert r["realistic_s"] == pytest.approx(base["realistic_s"] / (1 - share), abs=1)
    assert r["prudent_s"] == pytest.approx(base["prudent_s"] / (1 - share), abs=1)
    assert r["realistic_pace_s_km"] == base["realistic_pace_s_km"]
    assert r["aid_stations"][-1]["arrival_s"] == pytest.approx(r["realistic_s"], abs=1)
    assert r["segments"][-1]["passage_s"] == pytest.approx(r["realistic_s"], abs=1)
    zero = trail.predict_trail(profile, FLAT_MODEL, efforts, DAY, stops=stops,
                               aid_stations=[{"km": 10.0, "name": "R", "stop_min": 0.0}])
    assert zero["stops_source"] == "history"                     # ravito sans arrêt saisi
    own = trail.predict_trail(profile, FLAT_MODEL, efforts, DAY, stops=stops,
                              aid_stations=[{"km": 10.0, "name": "R", "stop_min": 2.0}])
    assert own["stops_source"] == "ravitos" and own["realistic_s"] == base["realistic_s"] + 120
    huge = trail.predict_trail(profile, FLAT_MODEL, efforts, DAY, stops={**stops, "a": 5.0})
    assert huge["stop_share_pct"] == trail.STOP_MAX_SHARE * 100


def test_validate_trail_replays_races_with_the_form_of_the_day_before():
    def act(i, day, terrain="road", **kw):
        bins = [[-2, 600, 1800], [0, 600, 1800], [10, 300, 600]]
        start = datetime.fromisoformat(day + "T09:00:00")
        return {"id": i, "name": f"s{i}", "start": start, "terrain": terrain,
                "grade_bins": json.dumps(bins), "distance_km": 10.0, "gain_m": 0.0, **kw}
    acts = [act(1, "2026-09-01"), act(2, "2026-09-10"), act(3, "2026-09-20"),
            act(10, "2026-10-10", "trail", moving_duration_s=3300, elapsed_s=3500),
            act(11, "2020-05-01", "trail", moving_duration_s=3000, elapsed_s=3300),
            act(12, "2026-10-20", "trail", moving_duration_s=3000, elapsed_s=3000)]
    efforts = [eff("distance", 10000, 3000, "2026-10-01"),
               eff("distance", 10000, 2000, "2026-10-10")]                 # le jour de la course : ignoré
    d = np.arange(0, 10001, 10.0)
    flat = {"distance": d, "altitude": np.zeros(d.size), "threshold_m": 3.5}
    races = [(acts[3], flat), (acts[4], flat), (acts[5], None)]
    v = trail.validate_trail(races, acts, efforts, {10, 11, 12})
    by_id = {r["activity_id"]: r for r in v["races"]}
    r = by_id[10]
    # part d'arrêt de la course 11 (même durée en mouvement) : 300 s sur 3 300
    assert r["estimate"]["moving_s"] == 3000 and r["estimate"]["realistic_s"] == 3300
    assert "segments" not in r["estimate"]
    assert r["error_pct"] == round((3300 / 3500 - 1) * 100, 1) and r["within"] is False
    assert r["moving_error_pct"] == round((3000 / 3300 - 1) * 100, 1)
    assert by_id[11]["reason"] == "pas de modèle allure-pente avant la course"
    assert by_id[12]["reason"] == "trace ou altitude indisponible"
    assert [x["date"] for x in v["races"]] == ["2026-10-20", "2026-10-10", "2020-05-01"]
    assert v["total"] == {"n": 1, "mae_pct": abs(r["error_pct"]), "bias_pct": r["error_pct"], "within": 0}
    assert v["moving"]["n"] == 1
    assert trail.validate_trail([], acts, efforts, set())["total"] is None
