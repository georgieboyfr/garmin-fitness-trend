"""
Allure ajustée à la pente (VAP) : l'allure équivalente sur le plat, pour le même effort
(fonctions pures).

Formule générique de Minetti (2002), base de la GAP de Strava : coût énergétique de la course
selon la pente, en J/kg/m. Chaque portion du profil est convertie en distance équivalente sur
le plat (distance × coût en pente / coût sur le plat), puis la VAP = temps en mouvement /
distance équivalente.

Limites connues : la formule ignore la technicité du terrain ; en forte descente, où l'on
ralentit pour des raisons de technique plus que d'énergie, la VAP sous-estime l'effort. Au-delà
de ±45 %, la pente est bornée (hors du domaine mesuré par Minetti).
"""
import numpy as np

MAX_GRADE = 0.45
GRADE_WINDOW_M = 50.0      # pente lissée sur 50 m : le pas de 10 m du profil est trop bruité
MOVING_MIN_MPS = 0.5       # même seuil que le temps en mouvement (metrics.MOVING_MIN_MPS)


def minetti_cost(grade) -> np.ndarray:
    """Coût énergétique de la course (J/kg/m) selon la pente (fraction : 0,1 = 10 %)."""
    i = np.clip(np.asarray(grade, dtype=float), -MAX_GRADE, MAX_GRADE)
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


FLAT_COST = float(minetti_cost(0.0))


def smoothed_grade(profile_distance, altitude, window_m=GRADE_WINDOW_M) -> np.ndarray:
    """Pente à chaque point du profil, mesurée entre ±window_m/2 autour du point."""
    d = np.asarray(profile_distance, dtype=float)
    alt = np.asarray(altitude, dtype=float)
    if d.size < 2:
        return np.zeros(d.size)
    half = window_m / 2
    lo = np.interp(np.clip(d - half, d[0], d[-1]), d, alt)
    hi = np.interp(np.clip(d + half, d[0], d[-1]), d, alt)
    span = np.clip(d + half, d[0], d[-1]) - np.clip(d - half, d[0], d[-1])
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(span > 0, (hi - lo) / span, 0.0)


def equivalent_distance(profile_distance, altitude) -> np.ndarray:
    """Distance équivalente sur le plat, cumulée à chaque point du profil (m)."""
    d = np.asarray(profile_distance, dtype=float)
    if d.size < 2:
        return np.zeros(d.size)
    grade = smoothed_grade(d, altitude)
    step_grade = (grade[1:] + grade[:-1]) / 2
    steps = np.diff(d) * minetti_cost(step_grade) / FLAT_COST
    return np.concatenate([[0.0], np.cumsum(steps)])


def gap_pace(t_at, profile_distance, altitude) -> float | None:
    """VAP en s/km sur le temps en mouvement (portions à au moins 0,5 m/s), ou None.
    t_at : temps écoulé (s) à chaque point du profil."""
    d = np.asarray(profile_distance, dtype=float)
    t_at = np.asarray(t_at, dtype=float)
    if d.size < 2:
        return None
    eq = np.diff(equivalent_distance(d, altitude))
    dt = np.diff(t_at)
    dd = np.diff(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        moving = (dt > 0) & (dd / dt >= MOVING_MIN_MPS)
    meters = eq[moving].sum()
    return float(dt[moving].sum() / meters * 1000) if meters > 100 else None
