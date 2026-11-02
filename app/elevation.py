"""
Calcul du D+ / D− d'une activité, commun aux deux sources d'altitude.

1. Profil altitude = f(distance) rééchantillonné à pas fixe (step_m) : la densité de
   points ne dépend plus de la montre (la Forerunner 255 enregistre un point toutes
   les quelques secondes, les autres chaque seconde) ni de l'allure.
2. Filtre médian (window points) : enlève les pics isolés.
3. Hystérésis : une montée (ou descente) n'est comptée qu'une fois qu'elle dépasse
   le seuil depuis le dernier extremum retenu. Le seuil dépend de la source : bruit
   du baromètre ou imprécision du MNT le long d'une trace GPS.

Changer l'algorithme = incrémenter ALGO_VERSION ; changer les réglages (admin) suffit
aussi à déclencher le recalcul, car ils sont enregistrés avec chaque résultat.
"""
import math

import numpy as np

ALGO_VERSION = 1

EARTH_RADIUS_M = 6_371_000.0


def cumulative_distance(lat, lon) -> np.ndarray:
    """Distance cumulée (m) le long d'une trace, par la formule de haversine."""
    lat = np.radians(np.asarray(lat, dtype=float))
    lon = np.radians(np.asarray(lon, dtype=float))
    if lat.size == 0:
        return np.zeros(0)
    dlat = np.diff(lat)
    dlon = np.diff(lon)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(dlon / 2) ** 2
    seg = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return np.concatenate([[0.0], np.cumsum(seg)])


def _clean_monotonic(distance, *columns):
    """Garde les points valides, triés par distance strictement croissante."""
    distance = np.asarray(distance, dtype=float)
    cols = [np.asarray(c, dtype=float) for c in columns]
    ok = np.isfinite(distance)
    for c in cols:
        ok &= np.isfinite(c)
    distance = distance[ok]
    cols = [c[ok] for c in cols]
    if distance.size == 0:
        return distance, cols
    # la distance d'un FIT peut stagner (arrêt) ou reculer légèrement : on ne garde que
    # les points qui font avancer la distance
    keep = np.concatenate([[True], distance[1:] > np.maximum.accumulate(distance)[:-1]])
    return distance[keep], [c[keep] for c in cols]


def resample(distance, values, step_m):
    """Rééchantillonne values(distance) tous les step_m mètres (interpolation linéaire)."""
    d, (v,) = _clean_monotonic(distance, values)
    if d.size < 2:
        return np.zeros(0), np.zeros(0)
    grid = np.arange(d[0], d[-1] + 1e-9, step_m)
    return grid, np.interp(grid, d, v)


def resample_positions(distance, lat, lon, step_m):
    """Points (lat, lon) tous les step_m mètres le long de la trace, pour interroger un MNT."""
    d, (la, lo) = _clean_monotonic(distance, lat, lon)
    if d.size < 2:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    grid = np.arange(d[0], d[-1] + 1e-9, step_m)
    return grid, np.interp(grid, d, la), np.interp(grid, d, lo)


def median_filter(values, window: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if window <= 1 or values.size < window:
        return values.copy()
    half = window // 2
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(windows, axis=1)


def hysteresis_gain_loss(values, threshold: float) -> tuple[float, float]:
    """D+ et D− en ne comptant que les variations supérieures au seuil."""
    gain = loss = 0.0
    if len(values) == 0:
        return gain, loss
    ref = float(values[0])
    for v in values[1:]:
        v = float(v)
        if v - ref >= threshold:
            gain += v - ref
            ref = v
        elif ref - v >= threshold:
            loss += ref - v
            ref = v
    return gain, loss


def gain_loss(distance, altitude, step_m, window, threshold) -> tuple[float, float]:
    """Chaîne complète : rééchantillonnage, filtre médian, hystérésis."""
    _, alt = resample(distance, altitude, step_m)
    if alt.size < 2:
        return 0.0, 0.0
    return hysteresis_gain_loss(median_filter(alt, window), threshold)


def series_distance(table) -> np.ndarray:
    """Distance cumulée d'une série : celle de la montre si présente, sinon calculée du GPS."""
    dist = table.column("distance_m").to_numpy(zero_copy_only=False).astype(float)
    if np.isfinite(dist).sum() >= 2:
        return dist
    lat = table.column("lat").to_numpy(zero_copy_only=False).astype(float)
    lon = table.column("lon").to_numpy(zero_copy_only=False).astype(float)
    ok = np.isfinite(lat) & np.isfinite(lon)
    out = np.full(lat.shape, math.nan)
    out[ok] = cumulative_distance(lat[ok], lon[ok])
    return out
