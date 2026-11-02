import math

import numpy as np
import pytest

from app.elevation import (
    cumulative_distance,
    gain_loss,
    hysteresis_gain_loss,
    median_filter,
    resample,
    resample_positions,
)


def test_hysteresis_ignores_small_oscillations():
    # bruit de ±1 m autour d'une montée de 100 m puis d'une descente de 50 m
    up = [i + (1 if i % 2 else -1) for i in range(0, 101)]
    down = [100 - i + (1 if i % 2 else -1) for i in range(1, 51)]
    gain, loss = hysteresis_gain_loss(up + down, threshold=3)
    assert gain == pytest.approx(100, abs=4)
    assert loss == pytest.approx(50, abs=4)
    # sans seuil, le bruit s'additionne : c'est le défaut du cumul brut
    raw_gain, _ = hysteresis_gain_loss(up + down, threshold=0)
    assert raw_gain > 140


def test_hysteresis_flat_and_empty():
    assert hysteresis_gain_loss([], 3) == (0.0, 0.0)
    assert hysteresis_gain_loss([200, 201, 199, 200.5], 3) == (0.0, 0.0)


def test_median_filter_removes_spike():
    values = [10, 10, 10, 40, 10, 10, 10]
    assert list(median_filter(values, 3)) == [10] * 7
    assert list(median_filter(values, 1)) == values


def test_resample_by_distance_ignores_stops_and_gaps():
    distance = [0, 10, 10, 20, math.nan, 40]       # arrêt à 10 m, point sans distance
    altitude = [100, 101, 150, 102, 103, 104]       # 150 : point d'arrêt ignoré
    grid, alt = resample(distance, altitude, 5)
    assert list(grid) == [0, 5, 10, 15, 20, 25, 30, 35, 40]
    assert alt[2] == pytest.approx(101) and alt[-1] == pytest.approx(104)


def test_resample_too_short():
    grid, alt = resample([0], [100], 10)
    assert grid.size == 0 and alt.size == 0


def test_cumulative_distance():
    # 0,001° de latitude ≈ 111 m
    d = cumulative_distance([45.0, 45.001, 45.002], [5.0, 5.0, 5.0])
    assert d[0] == 0 and d[1] == pytest.approx(111.2, abs=0.5) and d[2] == pytest.approx(222.4, abs=1)


def test_resample_positions():
    grid, lat, lon = resample_positions([0, 100], [45.0, 45.001], [5.0, 5.0], 50)
    assert list(grid) == [0, 50, 100]
    assert lat[1] == pytest.approx(45.0005)


def test_gain_loss_independent_of_sampling_density():
    # même montée de 200 m sur 2 km, échantillonnée toutes les 1 s ou toutes les 8 s
    rng = np.random.default_rng(0)
    for step in (3.0, 24.0):
        dist = np.arange(0, 2000 + step, step)
        alt = 300 + dist / 10 + rng.normal(0, 0.6, dist.size)
        gain, loss = gain_loss(dist, alt, step_m=10, window=5, threshold=2.5)
        assert gain == pytest.approx(200, abs=8)
        assert loss < 8
