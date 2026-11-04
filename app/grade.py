"""
Allure ajustée à la pente (VAP) : l'allure équivalente sur le plat, pour le même effort
(fonctions pures).

Courbe de Strava (2017, « An improved GAP model ») : facteur d'effort selon la pente, calé sur la
FC de millions de sorties et non sur le coût énergétique de Minetti (2002). Valeurs relevées par
Aaron Schroeder en envoyant à Strava des sorties à pente et vitesse constantes (paquet
specialsauce, licence MIT), interpolées linéairement. Chaque portion du profil est convertie en
distance équivalente sur le plat (distance × facteur), puis la VAP = temps en mouvement /
distance équivalente.

Différence avec Minetti : la descente la plus facile est vers −9 % (facteur 0,88) et non −18 %
(0,5) ; au-delà, l'effort remonte (×1,08 à −20 %, ×1,50 à −30 %), car la FC rend compte du
freinage et de la technique que le coût énergétique ignore. Limites : la technicité du terrain
n'est pas prise en compte ; au-delà de ±45 %, la pente est bornée (hors du domaine mesuré).
"""
import numpy as np

MAX_GRADE = 0.45
GRADE_WINDOW_M = 50.0      # pente lissée sur 50 m : le pas de 10 m du profil est trop bruité
MOVING_MIN_MPS = 0.5       # même seuil que le temps en mouvement (metrics.MOVING_MIN_MPS)


# pente (%) -> facteur : temps sur la pente / temps sur le plat, à effort égal
STRAVA_FACTORS = {
    -45: 2.096, -30: 1.495, -25: 1.273, -20: 1.081, -15: 0.941, -10: 0.876, -8: 0.876,
    -6: 0.891, -4: 0.918, -2: 0.96, 0: 1.0, 2: 1.055, 4: 1.135, 6: 1.228, 8: 1.337,
    10: 1.459, 15: 1.846, 20: 2.297, 25: 2.727, 30: 3.158, 45: 4.286,
}
_STRAVA_GRADES = np.array(list(STRAVA_FACTORS)) / 100
_STRAVA_VALUES = np.array(list(STRAVA_FACTORS.values()))


def strava_factor(grade) -> np.ndarray:
    """Facteur d'effort de Strava selon la pente (fraction : 0,1 = 10 %), 1 sur le plat."""
    i = np.clip(np.asarray(grade, dtype=float), -MAX_GRADE, MAX_GRADE)
    return np.interp(i, _STRAVA_GRADES, _STRAVA_VALUES)


def minetti_cost(grade) -> np.ndarray:
    """Coût énergétique de la course (J/kg/m) selon la pente (fraction : 0,1 = 10 %), Minetti
    (2002). Ne sert plus à la VAP : seulement à l'équivalent plat du D+ de l'estimateur route."""
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
    steps = np.diff(d) * strava_factor(step_grade)
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


GRADE_BIN = 0.02           # tranches de pente de 2 % (allure en descente, modèle allure-pente)


def grade_bins(t_at, profile_distance, altitude) -> list[list[float]]:
    """Temps en mouvement (s) et distance (m) par tranche de pente de 2 %, tranches vides omises :
    [[borne basse de la tranche en %, secondes, mètres], ...]. t_at : temps écoulé (s) à chaque
    point du profil. Pente lissée sur 50 m et bornée à ±45 %, comme pour la VAP."""
    d = np.asarray(profile_distance, dtype=float)
    t_at = np.asarray(t_at, dtype=float)
    if d.size < 2:
        return []
    g = smoothed_grade(d, altitude)
    step_grade = np.clip((g[1:] + g[:-1]) / 2, -MAX_GRADE, MAX_GRADE - 1e-9)
    dt = np.diff(t_at)
    dd = np.diff(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        moving = (dt > 0) & (dd / dt >= MOVING_MIN_MPS)
    idx = np.floor(step_grade / GRADE_BIN + 1e-9).astype(int)
    out = []
    for k in np.unique(idx[moving]):
        sel = moving & (idx == k)
        out.append([int(round(k * GRADE_BIN * 100)), round(float(dt[sel].sum()), 1),
                    round(float(dd[sel].sum()), 1)])
    return out
