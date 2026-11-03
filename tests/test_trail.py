import json
import math
from datetime import date, datetime

import numpy as np
import pytest

from app import estimator, trail
from app.track_parser import parse_route

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
    assert segs[0]["gain_m"] == 200 and segs[1]["loss_m"] == 200 and segs[0]["end_km"] == 2.0
    assert segs[-1]["passage_s"] == 2000 and segs[0]["time_s"] == round(2000 / 3)


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
    assert noisy["source"] == "gpx" and noisy["gain_m"] < 100               # bruit filtré par le seuil
    dem = trail.dem_altitudes(FakeDem(), lats, lons)
    p = trail.route_profile(lats, lons, eles, dem)
    assert p["source"] == "ign" and p["gain_m"] == pytest.approx(500, abs=10)
    assert trail.dem_altitudes(FakeDem(fail=True), lats, lons) is None
    assert trail.dem_altitudes(FakeDem(holes=0.2), lats, lons) is None      # MNT trop incomplet
