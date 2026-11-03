from datetime import UTC, date, datetime, timedelta

import numpy as np
import pyarrow as pa
import pytest

from app import db, elevation_job, metrics, metrics_job, processing

from .fit_builder import build_fit


def test_moving_time_excludes_stops_and_gaps():
    t = [0, 10, 20, 80, 90, 400, 410]
    d = [0, 30, 60, 60, 90, 120, 150]      # arrêt de 60 s, puis trou d'enregistrement de 310 s
    assert metrics.moving_time(t, d) == 10 + 10 + 10 + 10


def test_moving_time_slow_uphill_walk_counts():
    assert metrics.moving_time([0, 10], [0, 6]) == 10      # 0,6 m/s


def test_trimp_and_hrss_one_hour_at_lthr_is_100():
    t = np.arange(0, 3601, 1.0)
    hr = np.full(t.size, 170.0)
    tr = metrics.trimp(t, hr, 50, 190, "m")
    assert tr == pytest.approx(metrics.trimp_one_hour_at_lthr(50, 190, 170, "m"))
    assert metrics.hrss(tr, 50, 190, 170, "m") == pytest.approx(100)
    # une femme a un coefficient plus faible
    assert metrics.trimp(t, hr, 50, 190, "f") < tr


def test_trimp_ignores_long_gaps():
    assert metrics.trimp([0, 1000], [150, 150], 50, 190) == 0


def test_zone_times_on_lthr():
    # LTHR 170 : 140 -> Z1, 147 -> Z2, 155 -> Z3, 165 -> Z4, 175 -> Z5
    t = np.arange(0, 51, 1.0)
    hr = np.repeat([140, 147, 155, 165, 175], 10).astype(float)
    hr = np.append(hr, 175)
    z = metrics.zone_times(t, hr, 170)
    # chaque segment prend la FC moyenne de ses deux extrémités : la transition 165 -> 175
    # (moyenne 170 = LTHR) compte en Z5
    assert z == [10, 10, 10, 9, 11]


def test_best_average_hr():
    t = np.arange(0, 3600, 1.0)
    hr = np.where((t >= 1000) & (t < 2200), 175.0, 140.0)       # 20 min à 175
    assert metrics.best_average_hr(t, hr, 1200) == pytest.approx(175)
    assert metrics.best_average_hr(t, hr, 3600) is None          # sortie trop courte
    # un trou d'enregistrement au milieu de l'effort : la fenêtre n'est pas retenue
    keep = (t < 1500) | (t > 1600)
    assert metrics.best_average_hr(t[keep], hr[keep], 1200) < 175


def test_terrain():
    assert metrics.terrain(False, 8, 0) == "indoor"
    assert metrics.terrain(True, 10, 150) == "road"
    assert metrics.terrain(True, 10, 200) == "trail"


def test_activity_metrics_from_table():
    start = datetime(2026, 3, 1, 8, tzinfo=UTC)
    n = 600
    table = pa.table({
        "timestamp": [start + timedelta(seconds=i) for i in range(n)],
        "distance_m": [i * 3.0 for i in range(n)],
        "lat": [45.0] * n, "lon": [5.7] * n,
        "heart_rate": [160.0] * n,
    })
    m = metrics.activity_metrics(table, gain_m=10, hr_rest=50, hr_max=190, lthr=170)
    assert m["moving_s"] == 599 and m["elapsed_s"] == 599
    assert m["distance_km"] == pytest.approx(1.797)
    assert m["avg_hr"] == 160 and m["max_hr"] == 160
    assert m["hrss"] > 0 and m["terrain"] == "road"
    assert m["zones_s"][2] == pytest.approx(599)               # 160 / 170 = 94 % : Z3
    assert m["hr_best_20min"] is None


# ---------- calcul en base ----------

NOW = "2026-03-01T08:00:00Z"


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    yield c
    c.close()


class NoDem:
    def elevations(self, lats, lons):
        return np.full(len(lats), 300.0), "ign"


def add(conn, config, act_id, points, activity_type="running"):
    conn.execute(
        "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, fit_status,"
        " first_seen_at, updated_at) VALUES (?, ?, ?, ?, 'stored', ?, ?)",
        (act_id, NOW, "2026-03-01T09:00:00", activity_type, NOW, NOW))
    conn.commit()
    (config.fit_dir / f"{act_id}.fit").write_bytes(build_fit(points, garmin_product=3992))


def test_metrics_job_and_lthr_estimate(conn, config):
    pts = [{"t": i * 5, "distance_m": i * 15.0, "lat": 45.0 + i * 1e-4, "lon": 5.7,
            "altitude_m": 200.0, "heart_rate": 172 if 100 <= i < 820 else 150} for i in range(900)]
    add(conn, config, 1, pts)
    add(conn, config, 2, pts, activity_type="cycling")
    processing.parse_pending(config, conn, workers=1)
    elevation_job.compute_pending(config, conn, NoDem())
    assert metrics_job.compute_pending(config, conn) == {"metrics": 1}
    row = conn.execute("SELECT * FROM activity_metrics").fetchone()
    assert row["activity_id"] == 1 and row["terrain"] == "road"
    assert row["hr_best_60min"] == pytest.approx(172, abs=0.5)    # 60 min à 172
    assert metrics_job.compute_pending(config, conn) == {}
    est = metrics_job.lthr_estimate(conn, date(2026, 11, 3))
    assert est["best_60min"]["hr"] == 172 and est["max_hr"] == 172
    # changer la LTHR dans .env fait tout recalculer
    import dataclasses
    other = dataclasses.replace(config, lthr=175)
    assert metrics_job.pending_metrics(conn, other) == [1]


def test_efficiency_factor_and_decoupling():
    t = np.arange(0, 3601, 1.0)
    d = t * 3.0                                         # 180 m/min
    hr = np.full(t.size, 150.0)
    assert metrics.efficiency_factor(t, d, hr) == pytest.approx(180 / 150)
    assert metrics.decoupling(t, d, hr) == pytest.approx(0, abs=0.01)
    # même allure, FC qui monte de 150 à 165 en 2e moitié : 10 % d'EF perdu -> ~9 % de découplage
    drift = np.where(t < 1800, 150.0, 165.0)
    assert metrics.decoupling(t, d, drift) == pytest.approx((1 - 150 / 165) * 100, abs=0.2)
    assert metrics.decoupling(t[:1800], d[:1800], hr[:1800]) is None    # moins d'une heure
    assert metrics.efficiency_factor(t, d, np.full(t.size, np.nan)) is None
