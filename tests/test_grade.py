import numpy as np
import pytest

from app import grade


def test_minetti_cost_reference_values():
    assert grade.minetti_cost(0.0) == pytest.approx(3.6)
    assert grade.minetti_cost(0.1) == pytest.approx(6.0, abs=0.1)       # +10 % : 1,7 fois le plat
    assert grade.minetti_cost(-0.1) < 3.6                               # descente douce : moins cher
    assert grade.minetti_cost(0.8) == grade.minetti_cost(0.45)          # pente bornée


def test_gap_pace_flat_equals_pace():
    d = np.arange(0, 5001, 10.0)
    t_at = d / 3.0                                   # 3 m/s : 5'33" /km
    assert grade.gap_pace(t_at, d, np.zeros(d.size)) == pytest.approx(1000 / 3, rel=1e-6)


def test_gap_pace_uphill_is_faster_than_actual_pace():
    d = np.arange(0, 3001, 10.0)
    t_at = d / 2.0                                   # 2 m/s en montée à 10 %
    gap = grade.gap_pace(t_at, d, d * 0.1)
    assert gap == pytest.approx(500 * 3.6 / float(grade.minetti_cost(0.1)), rel=0.01)
    assert gap < 500


def test_gap_pace_ignores_stops_and_short_profiles():
    d = np.concatenate([np.arange(0, 2001, 10.0), np.full(30, 2000.0)])
    t_at = np.concatenate([np.arange(0, 2001, 10.0) / 2.5, 800 + np.arange(1, 31) * 20.0])   # 10 min d'arrêt
    assert grade.gap_pace(t_at, d, np.zeros(d.size)) == pytest.approx(400)
    assert grade.gap_pace([0, 10], [0, 50], [0, 0]) is None
