import numpy as np

from app import flyover

LAT0, LON0 = 45.0, 6.0
M_LAT = 1 / 111_195.0                              # degrés de latitude par mètre
M_LON = M_LAT / np.cos(np.radians(LAT0))


def track(xs, ys, speed=3.0):
    """Trace à partir de coordonnées locales (m), parcourue à vitesse constante."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))])
    return d / speed, LAT0 + ys * M_LAT, LON0 + xs * M_LON, d


def test_gaussian_smooth_keeps_constants_and_lines():
    assert np.allclose(flyover.gaussian_smooth(np.full(50, 7.0), 4), 7.0)
    line = np.arange(100.0)
    assert np.allclose(flyover.gaussian_smooth(line, 3)[20:80], line[20:80])
    assert np.array_equal(flyover.gaussian_smooth([1.0, 5.0], 0), [1.0, 5.0])


def test_straight_line_east_heading_90():
    t, lat, lon, d = track(np.arange(0, 3000, 2.0), np.zeros(1500))
    f = flyover.flyover(t, lat, lon, d)
    assert np.allclose(f["heading"], 90, atol=0.5)
    assert abs(f["km"][-1] - 2.998) < 0.01 and f["time_s"][-1] > 990


def test_circle_heading_is_continuous_across_north():
    """Deux tours de piste dans le sens horaire : le cap croît sans saut de 360°."""
    a = np.linspace(0, 4 * np.pi, 4000)
    r = 200.0
    t, lat, lon, d = track(r * np.sin(a), r * np.cos(a))
    h = np.array(flyover.flyover(t, lat, lon, d)["heading"])
    assert np.abs(np.diff(h)).max() < 5
    assert 600 < h[-1] - h[0] < 760               # deux tours, bords lissés


def test_switchbacks_keep_the_general_direction():
    """Lacets de 40 m vers le nord : le cap de la caméra reste proche du nord, loin des ±90°."""
    xs, ys = [], []
    for k in range(40):
        y = k * 20.0
        side = 40.0 if k % 2 else -40.0
        xs += list(np.linspace(-side, side, 40))
        ys += list(np.linspace(y, y + 20, 40))
    t, lat, lon, d = track(xs, ys)
    h = np.array(flyover.flyover(t, lat, lon, d)["heading"])
    middle = h[len(h) // 5: -len(h) // 5]
    wrapped = (middle + 180) % 360 - 180
    assert np.abs(wrapped).max() < 45


def test_u_turn_is_progressive():
    """Aller-retour : le cap tourne de 180° en plusieurs centaines de mètres, sans à-coup."""
    xs = np.concatenate([np.zeros(1000), np.full(1000, 1.5)])
    ys = np.concatenate([np.arange(0, 2000, 2.0), np.arange(2000, 0, -2.0)])
    t, lat, lon, d = track(xs, ys)
    f = flyover.flyover(t, lat, lon, d)
    h = np.array(f["heading"])
    assert abs(abs(h[-1] - h[0]) - 180) < 5
    assert np.abs(np.diff(h)).max() < 180 * f["step_m"] / 300


def test_gps_noise_is_smoothed_and_altitude_gives_grade():
    rng = np.random.default_rng(1)
    xs = np.arange(0, 2000, 1.0)
    _, lat, lon, _ = track(xs + rng.normal(0, 3, xs.size), rng.normal(0, 3, xs.size))
    f = flyover.flyover(xs / 3.0, lat, lon, xs, hr=np.full(xs.size, 150.0),
                        alt_distance=xs, alt=500 + xs * 0.08)
    lat_m = (np.array(f["lat"]) - LAT0) / M_LAT
    assert np.std(lat_m[20:-20]) < 2
    assert abs(np.nanmedian(np.array(f["grade"], float)) - 8) < 0.5
    assert f["hr"][10] == 150 and abs(f["pace"][len(f["pace"]) // 2] - 333) <= 3


def test_no_usable_track():
    assert flyover.flyover([0, 1], [np.nan, np.nan], [np.nan, np.nan], [0, 3]) is None
    t, lat, lon, d = track(np.arange(0, 20.0), np.zeros(20))
    assert flyover.flyover(t, lat, lon, d) is None


def test_point_count_is_capped():
    t, lat, lon, d = track(np.arange(0, 100_000, 5.0), np.zeros(20_000))
    f = flyover.flyover(t, lat, lon, d)
    assert len(f["lat"]) <= flyover.MAX_POINTS and f["step_m"] > 20
