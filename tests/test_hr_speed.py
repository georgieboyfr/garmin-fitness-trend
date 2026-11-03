import numpy as np
import pytest

from app import hr_speed


def run(speeds_by_minute, hr_of_speed, hr_offset=0.0):
    """Série à 1 s : vitesse constante par minute, FC = f(vitesse) + décalage."""
    v = np.repeat(np.asarray(speeds_by_minute, dtype=float), 60)
    t = np.arange(v.size + 1, dtype=float)
    d = np.concatenate([[0.0], np.cumsum(v)])
    hr = np.concatenate([[hr_of_speed(v[0])], hr_of_speed(v)]) + hr_offset
    return t, d, hr


def line(v):
    return 80 + 25 * v


def test_steady_blocks_skip_warmup_and_pace_changes():
    # 15 min à 3 m/s, puis 5 min à 4 m/s
    t, d, hr = run([3.0] * 15 + [4.0] * 5, line)
    blocks = hr_speed.steady_blocks(t, d, hr)
    speeds = [b[0] for b in blocks]
    assert speeds.count(3.0) == 5                     # minutes 10 à 14 : après l'échauffement
    assert speeds.count(4.0) == 3                     # la 1re minute à 4 m/s et la suivante attendent
    assert all(h == pytest.approx(line(v)) for v, h in blocks)


def test_steady_blocks_no_hr_or_too_short():
    t, d, hr = run([3.0] * 20, line)
    assert hr_speed.steady_blocks(t, d, np.full(t.size, np.nan)) == []
    assert hr_speed.steady_blocks(t[:300], d[:300], hr[:300]) == []
    hr_gap = hr.copy()
    hr_gap[700:760] = np.nan                          # une minute sans FC : bloc écarté
    assert len(hr_speed.steady_blocks(t, d, hr_gap)) < len(hr_speed.steady_blocks(t, d, hr))


def test_fit_and_assess():
    rng = np.random.default_rng(1)
    history = [(v, line(v) + rng.normal(0, 2)) for v in rng.uniform(2.5, 4.0, 300)]
    model = hr_speed.fit(history)
    assert model["b"] == pytest.approx(25, rel=0.1) and model["a"] == pytest.approx(80, abs=4)
    good = [(v, line(v) - 6) for v in np.linspace(2.8, 3.6, 20)]
    res = hr_speed.assess(model, good)
    assert res["verdict"] == "better" and res["hr_diff"] == pytest.approx(-6, abs=1)
    assert res["speed_pct"] > 0                        # à FC égale, plus rapide
    assert hr_speed.assess(model, [(v, line(v) + 1) for v in np.linspace(3, 3.5, 10)])["verdict"] == "same"
    assert hr_speed.assess(model, [(v, line(v) + 8) for v in np.linspace(3, 3.5, 10)])["verdict"] == "worse"
    assert hr_speed.assess(model, good[:3]) is None   # trop peu de portions
    assert hr_speed.assess(None, good) is None
    assert hr_speed.fit(history[:20]) is None


def test_steady_blocks_skip_recovery_after_faster_effort():
    # 12 min à 3 m/s, 3 min à 4,5 m/s, puis récupération à 2,5 m/s
    t, d, hr = run([3.0] * 12 + [4.5] * 3 + [2.5] * 6, line)
    recovery = [b for b in hr_speed.steady_blocks(t, d, hr) if b[0] == 2.5]
    assert len(recovery) == 3                         # sans la règle : 4 (la minute à +2 min est écartée)
