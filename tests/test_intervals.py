import numpy as np

from app import intervals


def session(efforts=4, effort_s=300, rest_s=120, fast=4.2, slow=2.7, warm_s=600):
    """Séance synthétique : échauffement, efforts et récupérations, retour au calme."""
    speeds = [slow] * warm_s
    for k in range(efforts):
        speeds += [fast] * effort_s
        if k + 1 < efforts:
            speeds += [slow] * rest_s
    speeds += [slow] * warm_s
    t = np.arange(len(speeds) + 1, dtype=float)
    d = np.concatenate([[0], np.cumsum(speeds)])
    hr = np.where(np.concatenate([[slow], speeds]) > 3.5, 170.0, 140.0)
    return t, d, hr


def test_detects_regular_efforts():
    rows = intervals.detect(*session())
    kinds = [r["kind"] for r in rows]
    assert kinds.count("effort") == 4 and kinds.count("récupération") == 3
    assert kinds[0] == "échauffement" and kinds[-1] == "retour au calme"
    efforts = [r for r in rows if r["kind"] == "effort"]
    assert all(abs(r["duration_s"] - 300) <= 20 for r in efforts)
    s = intervals.summary(rows)
    assert s["count"] == 4 and abs(s["pace_s_km"] - 1000 / 4.2) < 10


def test_steady_run_is_not_intervals():
    t = np.arange(3601, dtype=float)
    assert intervals.detect(t, t * 3.0, np.full(t.size, 150.0)) is None


def test_irregular_surges_are_not_intervals():
    # trois accélérations de durées très différentes (côte, relance...) : pas une séance
    rows = intervals.detect(*session(efforts=3, effort_s=300)[:2], None)
    assert rows is not None                                   # la séance régulière passe
    speeds = [2.7] * 600 + [4.2] * 45 + [2.7] * 300 + [4.2] * 600 + [2.7] * 300 + [4.2] * 120 + [2.7] * 600
    t = np.arange(len(speeds) + 1, dtype=float)
    assert intervals.detect(t, np.concatenate([[0], np.cumsum(speeds)]), None) is None


def test_structured_laps():
    def lap(duration, distance, avg, mx, intensity):
        return {"duration_s": duration, "distance_m": distance, "avg_hr": avg, "max_hr": mx,
                "intensity": intensity, "trigger": "x"}

    laps = [lap(600, 1800, 140, 150, "warmup"), lap(240, 1000, 170, 176, "active"),
            lap(180, 450, 150, 165, "rest")]
    rows = intervals.from_laps(laps)
    assert [r["kind"] for r in rows] == ["échauffement", "effort", "récupération"]
    assert rows[1]["start_s"] == 600
    auto = [{**lap, "intensity": "interval", "trigger": "distance"} for lap in laps]
    assert intervals.from_laps(auto) is None                  # tours automatiques : ignorés
    manual = [{**lap, "intensity": None, "trigger": "manual"} for lap in laps]
    assert [r["kind"] for r in intervals.from_laps(manual)] == ["tour"] * 3
