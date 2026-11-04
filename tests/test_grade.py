import numpy as np
import pytest

from app import grade


def test_minetti_cost_reference_values():
    assert grade.minetti_cost(0.0) == pytest.approx(3.6)
    assert grade.minetti_cost(0.1) == pytest.approx(6.0, abs=0.1)       # +10 % : 1,7 fois le plat
    assert grade.minetti_cost(-0.1) < 3.6                               # descente douce : moins cher
    assert grade.minetti_cost(0.8) == grade.minetti_cost(0.45)          # pente bornée


def test_strava_factor_reference_values():
    assert grade.strava_factor(0.0) == pytest.approx(1.0)
    assert grade.strava_factor(0.1) == pytest.approx(1.459)
    assert grade.strava_factor(-0.09) == pytest.approx(0.876)          # descente la plus facile
    assert grade.strava_factor(-0.2) > 1.0                              # descente raide : plus dur
    assert grade.strava_factor(-0.3) > float(grade.minetti_cost(-0.3)) / grade.FLAT_COST
    assert grade.strava_factor(0.05) == pytest.approx((1.135 + 1.228) / 2)
    assert grade.strava_factor(-0.8) == grade.strava_factor(-0.45)      # pente bornée


def test_gap_pace_steep_downhill_is_faster_than_actual_pace():
    d = np.arange(0, 2001, 10.0)
    t_at = d / 2.5                                   # 2,5 m/s en descente à −30 %
    gap = grade.gap_pace(t_at, d, -d * 0.3)
    assert gap == pytest.approx(400 / 1.495, rel=0.01)


def test_gap_pace_flat_equals_pace():
    d = np.arange(0, 5001, 10.0)
    t_at = d / 3.0                                   # 3 m/s : 5'33" /km
    assert grade.gap_pace(t_at, d, np.zeros(d.size)) == pytest.approx(1000 / 3, rel=1e-6)


def test_gap_pace_uphill_is_faster_than_actual_pace():
    d = np.arange(0, 3001, 10.0)
    t_at = d / 2.0                                   # 2 m/s en montée à 10 %
    gap = grade.gap_pace(t_at, d, d * 0.1)
    assert gap == pytest.approx(500 / 1.459, rel=0.01)
    assert gap < 500


def test_gap_pace_ignores_stops_and_short_profiles():
    d = np.concatenate([np.arange(0, 2001, 10.0), np.full(30, 2000.0)])
    t_at = np.concatenate([np.arange(0, 2001, 10.0) / 2.5, 800 + np.arange(1, 31) * 20.0])   # 10 min d'arrêt
    assert grade.gap_pace(t_at, d, np.zeros(d.size)) == pytest.approx(400)
    assert grade.gap_pace([0, 10], [0, 50], [0, 0]) is None


def test_grade_bins_split_moving_time_by_slope():
    d = np.arange(0, 2001, 10.0)
    alt = np.where(d <= 1000, 0.0, -(d - 1000) * 0.07)            # 1 km plat puis 1 km à −7 %
    t_at = np.where(d <= 1000, d / 3.0, 1000 / 3.0 + (d - 1000) / 4.0)
    bins = {b[0]: b for b in grade.grade_bins(t_at, d, alt)}
    assert set(bins) <= {0, -2, -4, -6, -8}                      # transition lissée sur 50 m
    assert bins[0][2] == pytest.approx(1000, abs=40) and bins[-8][2] == pytest.approx(1000, abs=40)
    assert bins[-8][1] == pytest.approx(bins[-8][2] / 4.0, rel=0.01)
    assert sum(b[2] for b in bins.values()) == pytest.approx(2000)


def test_grade_bins_ignore_stops():
    d = np.concatenate([np.arange(0, 1001, 10.0), np.full(10, 1000.0)])
    t_at = np.concatenate([np.arange(0, 1001, 10.0) / 2.5, 400 + np.arange(1, 11) * 30.0])
    assert grade.grade_bins(t_at, d, np.zeros(d.size)) == [[0, 400.0, 1000.0]]
    assert grade.grade_bins([0], [0], [0]) == []
