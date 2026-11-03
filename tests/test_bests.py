import numpy as np
import pytest

from app import bests


def steady(n_s, speed, start_d=0.0):
    t = np.arange(0, n_s + 1, 1.0)
    return t, start_d + t * speed


def test_best_time_for_distance_inside_longer_run():
    # 15 min à 3 m/s, puis 20 min à 4 m/s, puis 15 min à 3 m/s : le meilleur 3 km est au milieu
    t1, d1 = steady(900, 3.0)
    t2, d2 = steady(1200, 4.0, d1[-1])
    t3, d3 = steady(900, 3.0, d2[-1])
    t = np.concatenate([t1, t2[1:] + 900, t3[1:] + 2100])
    d = np.concatenate([d1, d2[1:], d3[1:]])
    time, start = bests.best_time_for_distance(t, d, 3000)
    assert time == pytest.approx(750)            # 3000 m / 4 m/s
    assert 900 <= start <= 1350
    assert bests.best_time_for_distance(t, d, 50000) is None


def test_best_distance_for_duration():
    t, d = steady(3600, 3.0)
    assert bests.best_distance_for_duration(t, d, 1200) == pytest.approx(3600)
    assert bests.best_distance_for_duration(t, d, 7200) is None


def test_gps_spike_does_not_create_a_record():
    t, d = steady(1200, 3.0)
    d = d.copy()
    d[600:] += 500                               # saut de position de 500 m en 1 s
    tc, dc = bests.clean_distance(t, d)
    assert dc[-1] == pytest.approx(3597)         # le segment du saut est ignoré en entier
    time, _ = bests.best_time_for_distance(tc, dc, 1000)
    assert time == pytest.approx(1000 / 3)


def test_turning_points_and_climbs():
    # 0 -> 300 m (avec un replat et une petite descente de 10 m), -> 100 m, -> 160 m
    alt = np.concatenate([np.linspace(0, 150, 50), np.linspace(150, 140, 5), np.linspace(140, 300, 50),
                          np.linspace(300, 100, 60), np.linspace(100, 160, 20)])
    pts = bests.turning_points(alt, 20)
    assert [round(alt[p]) for p in pts] == [0, 300, 100, 160]
    t_at = np.arange(alt.size) * 10.0             # 10 s par point
    found = bests.climbs(t_at, alt)
    assert len(found) == 1                        # la remontée de 60 m est trop courte
    assert found[0]["gain_m"] == pytest.approx(300)
    assert found[0]["vam_mh"] == pytest.approx(300 / (104 * 10) * 3600)


def test_activity_bests_rows():
    t, d = steady(4000, 3.0)
    profile_d = np.arange(0, 12000, 10.0)
    profile_alt = profile_d * 0.05                # 5 % de pente continue : 600 m de D+
    rows = bests.activity_bests(t, d, profile_d, profile_alt)
    kinds = {(r["kind"], r["key"]) for r in rows}
    assert ("distance", 10000) in kinds and ("distance", 21097.5) not in kinds
    assert ("duration", 3600) in kinds and ("duration", 7200) not in kinds
    climb = [r for r in rows if r["kind"] == "climb"][0]
    assert climb["extra"] == pytest.approx(600, abs=1)
    assert climb["value"] == pytest.approx(600 / 4000 * 3600, rel=0.01)
    # sans profil d'altitude : pas de VAM
    assert not [r for r in bests.activity_bests(t, d) if r["kind"] == "climb"]


def test_best_climb_for_gain_inside_one_climb():
    # montée de 300 m : 100 m lents (1 m / 10 s), 100 m rapides (1 m / 5 s), 100 m lents,
    # coupée par une descente de 10 m (ignorée), puis une descente de 200 m et une remontée de 150 m
    alt = np.concatenate([np.arange(0, 100), np.arange(100, 200), np.arange(200, 190, -1),
                          np.arange(190, 300), np.arange(300, 100, -1), np.arange(100, 251)]).astype(float)
    step = np.concatenate([np.full(100, 10.0), np.full(100, 5.0), np.full(10, 5.0), np.full(110, 10.0),
                           np.full(200, 5.0), np.full(151, 6.0)])
    t_at = np.concatenate([[0.0], np.cumsum(step[:-1])])
    time, start = bests.best_climb_for_gain(t_at, alt, 100)
    assert time == pytest.approx(500)            # les 100 m rapides
    assert start == pytest.approx(1000)
    time200, _ = bests.best_climb_for_gain(t_at, alt, 200)
    assert time200 < 2000                        # la petite descente n'interrompt pas la montée
    assert bests.best_climb_for_gain(t_at, alt, 500) is None


def test_window_avg_hr():
    t = np.arange(0, 601, 1.0)
    hr = np.where(t < 300, 120.0, 160.0)
    assert bests.window_avg_hr(t, hr, 300, 300) == pytest.approx(160, abs=0.2)
    assert bests.window_avg_hr(t, hr, 0, 600) == pytest.approx(140, abs=0.2)
    assert bests.window_avg_hr(t, np.full(t.size, np.nan), 0, 600) is None   # pas de FC
    assert bests.window_avg_hr(t, hr, 0, 600) is not None
    assert bests.window_avg_hr(t, None, 0, 600) is None


def test_activity_bests_heart_rate_and_climb_steps():
    t, d = steady(4000, 3.0)
    profile_d = np.arange(0, 12000, 10.0)
    rows = bests.activity_bests(t, d, profile_d, profile_d * 0.05, hr=np.full(t.size, 150.0))
    by_key = {(r["kind"], r["key"]): r for r in rows}
    assert by_key[("distance", 1000)]["avg_hr"] == pytest.approx(150)
    assert by_key[("climb", 0)]["avg_hr"] == pytest.approx(150)
    assert {k for kind, k in by_key if kind == "climb"} == {0, 100, 200, 500}   # pas de palier de 1000 m
    assert by_key[("climb", 500)]["value"] == pytest.approx(600 / 4000 * 3600, rel=0.02)


def test_clean_altitude_ignores_impossible_jumps():
    t_at = np.array([0, 10, 20, 20, 30, 40], dtype=float)
    alt = np.array([100, 105, 110, 150, 155, 160], dtype=float)   # +40 m sans temps écoulé
    assert list(bests.clean_altitude(t_at, alt)) == [100, 105, 110, 110, 115, 120]
    fast = np.array([100, 105, 160, 165], dtype=float)            # +55 m en 10 s : saut
    assert list(bests.clean_altitude(np.array([0, 10, 20, 30.0]), fast)) == [100, 105, 105, 110]


def test_climb_vam_with_gps_spike_stays_plausible():
    # 1 m/s de vitesse, 10 % de pente (360 m/h), et un saut GPS de 500 m au milieu :
    # la distance brute du profil dépasse la distance nettoyée, le temps doit rester cohérent
    t, d = steady(4000, 1.0)
    d = d.copy()
    d[2000:] += 500
    profile_d = np.arange(0, d[-1], 10.0)
    after = np.where(profile_d < 2500, 200, (profile_d - 500) * 0.1)
    alt = np.where(profile_d < 2000, profile_d * 0.1, after)
    rows = bests.activity_bests(t, d, profile_d, alt)
    vams = [r["value"] for r in rows if r["kind"] == "climb"]
    assert vams and max(vams) < 400
