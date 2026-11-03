import numpy as np
import pytest

from app import db, elevation_job, processing, settings
from app.dem import DemUnavailable

from .fit_builder import build_fit

NOW = "2026-03-01T08:00:00Z"


class FakeDem:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def elevations(self, lats, lons):
        self.calls += 1
        if self.fail:
            raise DemUnavailable("hors ligne")
        # terrain : monte de 1 m tous les 10 m vers le nord
        return 200 + (np.asarray(lats) - 45.0) * 111_000 / 10, "ign"


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    yield c
    c.close()


def add(conn, config, act_id, points, product, activity_type="running"):
    conn.execute(
        "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, fit_status,"
        " first_seen_at, updated_at) VALUES (?, ?, ?, ?, 'stored', ?, ?)",
        (act_id, NOW, NOW, activity_type, NOW, NOW),
    )
    conn.commit()
    (config.fit_dir / f"{act_id}.fit").write_bytes(build_fit(points, garmin_product=product))


def climb(n=101, with_alt=True, with_gps=True):
    # 1 km vers le nord (0,009° ≈ 1 000 m), altitude baromètre : +100 m
    return [{"t": i, "distance_m": i * 10.0,
             "lat": 45.0 + i * 0.00009 if with_gps else None, "lon": 5.7 if with_gps else None,
             "altitude_m": 200.0 + i if with_alt else None, "heart_rate": 150} for i in range(n)]


def results(conn):
    return {r["activity_id"]: dict(r) for r in conn.execute("SELECT * FROM activity_elevation")}


def test_sources_by_device(conn, config):
    add(conn, config, 1, climb(), product=3992)                     # Forerunner 255 : baromètre
    add(conn, config, 2, climb(), product=3076)                     # Forerunner 245 : altitude GPS -> MNT
    add(conn, config, 3, climb(with_alt=False), product=2503)       # Forerunner 35 : MNT
    add(conn, config, 4, climb(with_gps=False, with_alt=False), product=3992,
        activity_type="treadmill_running")                          # tapis
    add(conn, config, 5, climb(), product=3992, activity_type="cycling")  # hors course à pied
    processing.parse_pending(config, conn, workers=1)
    dem = FakeDem()
    counts = elevation_job.compute_pending(config, conn, dem)
    assert counts == {"elevation": 4}
    r = results(conn)
    assert set(r) == {1, 2, 3, 4}
    assert r[1]["source"] == "barometer" and r[1]["gain_m"] == pytest.approx(100, abs=3)
    assert r[2]["source"] == "dem" and r[2]["dem_provider"] == "ign"
    assert r[2]["gain_m"] == pytest.approx(100, abs=5)
    assert r[3]["source"] == "dem"
    assert r[4]["source"] == "none" and r[4]["gain_m"] == 0
    assert dem.calls == 2


def test_dem_profile_is_cached_and_params_change_recomputes(conn, config):
    add(conn, config, 2, climb(), product=3076)
    processing.parse_pending(config, conn, workers=1)
    dem = FakeDem()
    elevation_job.compute_pending(config, conn, dem)
    assert elevation_job.compute_pending(config, conn, dem) == {}
    settings.update(conn, "elevation", {"threshold_dem": 6.0})
    assert elevation_job.pending_elevation(conn) == [2]
    assert elevation_job.compute_pending(config, conn, dem) == {"elevation": 1}
    assert dem.calls == 1  # profil MNT réutilisé depuis le cache
    assert '"threshold_dem": 6.0' in results(conn)[2]["params"]


def test_new_algo_version_recomputes(conn, config, monkeypatch):
    add(conn, config, 1, climb(), product=3992)
    processing.parse_pending(config, conn, workers=1)
    elevation_job.compute_pending(config, conn, FakeDem())
    monkeypatch.setattr(elevation_job, "ALGO_VERSION", elevation_job.ALGO_VERSION + 1)
    assert elevation_job.pending_elevation(conn) == [1]


def test_dem_unavailable_postpones(conn, config):
    add(conn, config, 2, climb(), product=3076)
    processing.parse_pending(config, conn, workers=1)
    assert elevation_job.compute_pending(config, conn, FakeDem(fail=True)) == {"elevation_postponed": 1}
    assert results(conn) == {}
    assert elevation_job.compute_pending(config, conn, FakeDem()) == {"elevation": 1}


def test_elevation_settings_validation(conn):
    assert settings.update(conn, "elevation", {"window": 7})["window"] == 7
    for bad in [{"window": 4}, {"step_m": 1}, {"threshold_dem": -1}, {"threshold_barometer": "2"}]:
        with pytest.raises(ValueError):
            settings.update(conn, "elevation", bad)


class AbroadDem(FakeDem):
    def elevations(self, lats, lons):
        z, _ = super().elevations(lats, lons)
        return z, "copernicus"


def test_strava_gain_preferred_abroad(conn, config):
    add(conn, config, 2, climb(), product=3076)
    processing.parse_pending(config, conn, workers=1)
    elevation_job.compute_pending(config, conn, AbroadDem())
    assert results(conn)[2]["source"] == "dem"
    # l'export Strava arrive ensuite : le D+ de Strava remplace celui de Copernicus
    conn.execute("INSERT INTO strava_activities (strava_id, start_time_utc, name, elevation_gain_m,"
                 " activity_id, updated_at) VALUES (9, ?, 'Rome', 42.0, 2, ?)", (NOW, NOW))
    conn.commit()
    assert elevation_job.pending_elevation(conn) == [2]
    dem = AbroadDem()
    elevation_job.compute_pending(config, conn, dem)
    r = results(conn)[2]
    assert (r["source"], r["gain_m"], r["loss_m"]) == ("strava", 42.0, None)
    assert dem.calls == 0                                   # profil MNT en cache
    assert elevation_job.pending_elevation(conn) == []


def test_strava_gain_ignored_in_france(conn, config):
    add(conn, config, 2, climb(), product=3076)
    conn.execute("INSERT INTO strava_activities (strava_id, start_time_utc, name, elevation_gain_m,"
                 " activity_id, updated_at) VALUES (9, ?, 'Bastille', 42.0, 2, ?)", (NOW, NOW))
    conn.commit()
    processing.parse_pending(config, conn, workers=1)
    elevation_job.compute_pending(config, conn, FakeDem())
    assert results(conn)[2]["source"] == "dem"              # en France, l'IGN fait foi
