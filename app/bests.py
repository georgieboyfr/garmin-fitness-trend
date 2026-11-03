"""
Meilleurs efforts à l'intérieur d'une sortie, en fenêtre glissante (fonctions pures).

- Distances (1, 3, 5, 10, 21,1, 42,2 km) : temps le plus court pour parcourir la distance,
  n'importe où dans la sortie (ton meilleur 5 km est peut-être au milieu d'un 15 km).
  Temps écoulé : les arrêts pendant l'effort comptent.
- Durées (1, 5, 20 min, 1 h, 2 h) : plus grande distance parcourue, d'où la meilleure
  allure tenue sur cette durée (courbe allure-durée).
- Montées de plus de 200 m de D+ : VAM (vitesse ascensionnelle, m/h).
- Paliers de montée (100, 200, 500, 1000 m de D+) : temps le plus court pour s'élever de ce
  dénivelé à l'intérieur d'une même montée (les descentes de moins de 20 m ne l'interrompent
  pas), d'où la VAM.
- FC moyenne sur chaque effort (distances et montées), pondérée par le temps.

Filtrage des pics GPS : un segment plus rapide que MAX_SPEED_MPS (sprint impossible en
course à pied, typiquement un saut de position) ne fait pas avancer la distance. Le
défaut est de ralentir légèrement l'effort, jamais de créer un faux record.
"""
import numpy as np

DISTANCES_M = (1000, 3000, 5000, 10000, 21097.5, 42195)
DURATIONS_S = (60, 300, 1200, 3600, 7200)
MAX_SPEED_MPS = 7.0            # 2'23" /km
CLIMB_MIN_GAIN_M = 200.0
CLIMB_DIP_M = 20.0             # une descente de moins de 20 m n'interrompt pas une montée
CLIMB_GAINS_M = (100, 200, 500, 1000)
MAX_VERTICAL_MPS = 1.0         # 3600 m/h : au-delà, saut d'altitude (GPS ou MNT), pas une montée


def clean_distance(t, distance) -> tuple[np.ndarray, np.ndarray]:
    """(t, distance cumulée) sans pics GPS, distance croissante, points sans distance retirés."""
    t = np.asarray(t, dtype=float)
    d = np.asarray(distance, dtype=float)
    ok = np.isfinite(t) & np.isfinite(d)
    t, d = t[ok], d[ok]
    if t.size < 2:
        return t, d
    dt = np.diff(t)
    dd = np.diff(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        bad = (dd < 0) | ((dt > 0) & (dd / dt > MAX_SPEED_MPS)) | ((dt <= 0) & (dd > 0))
    dd = np.where(bad, 0.0, dd)
    return t, np.concatenate([[d[0]], d[0] + np.cumsum(dd)])


def best_time_for_distance(t, d, distance_m) -> tuple[float, float] | None:
    """(meilleur temps en s, instant de départ en s) pour parcourir distance_m, ou None."""
    if d.size < 2 or d[-1] - d[0] < distance_m:
        return None
    # pour chaque départ i, premier point j où l'on a parcouru la distance, avec interpolation
    target = d + distance_m
    j = np.searchsorted(d, target, side="left")
    valid = j < d.size
    if not valid.any():
        return None
    i = np.nonzero(valid)[0]
    j = j[valid]
    d0, d1 = d[j - 1], d[j]
    t0, t1 = t[j - 1], t[j]
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(d1 > d0, (target[i] - d0) / (d1 - d0), 0.0)
    times = (t0 + frac * (t1 - t0)) - t[i]
    k = int(np.argmin(times))
    return float(times[k]), float(t[i[k]])


def best_distance_for_duration(t, d, duration_s) -> float | None:
    """Plus grande distance (m) parcourue en duration_s secondes consécutives, ou None."""
    if t.size < 2 or t[-1] - t[0] < duration_s:
        return None
    end = np.interp(t + duration_s, t, d)      # distance au bout de la fenêtre
    valid = t + duration_s <= t[-1]
    return float((end - d)[valid].max()) if valid.any() else None


def turning_points(values, threshold) -> list[int]:
    """Indices des extrema successifs (minimum, maximum, minimum...) : une variation n'est
    retenue que si elle dépasse le seuil (hystérésis)."""
    v = values
    if len(v) == 0:
        return []
    lo = hi = 0          # avant la première variation significative : plus bas et plus haut vus
    points, direction, ext = [], 0, 0
    for k in range(1, len(v)):
        if direction == 0:
            lo = k if v[k] < v[lo] else lo
            hi = k if v[k] > v[hi] else hi
            if v[k] - v[lo] >= threshold:
                points, direction, ext = [lo], 1, k
            elif v[hi] - v[k] >= threshold:
                points, direction, ext = [hi], -1, k
        elif direction == 1:
            if v[k] > v[ext]:          # strict : sur un plateau, l'extremum est son premier point
                ext = k
            elif v[ext] - v[k] >= threshold:
                points.append(ext)
                direction, ext = -1, k
        else:
            if v[k] < v[ext]:
                ext = k
            elif v[k] - v[ext] >= threshold:
                points.append(ext)
                direction, ext = 1, k
    if direction:
        points.append(ext)
    return points


def climbs(t_at, altitude, min_gain=CLIMB_MIN_GAIN_M, dip=CLIMB_DIP_M) -> list[dict]:
    """Montées d'au moins min_gain mètres (altitude filtrée, échantillonnée à pas de distance
    régulier ; t_at = temps écoulé à chaque point) : gain, durée, VAM."""
    alt = np.asarray(altitude, dtype=float)
    pts = turning_points(alt, dip)
    out = []
    for a, b in zip(pts, pts[1:], strict=False):
        gain = alt[b] - alt[a]
        duration = t_at[b] - t_at[a]
        if gain >= min_gain and duration > 0:
            out.append({"gain_m": float(gain), "duration_s": float(duration),
                        "vam_mh": float(gain / duration * 3600), "start_s": float(t_at[a])})
    return out


def clean_altitude(t_at, altitude) -> np.ndarray:
    """Altitude sans sauts : une montée plus rapide que MAX_VERTICAL_MPS (ou sans temps écoulé) est
    ramenée à zéro, comme les pics GPS pour la distance. Le défaut est de sous-estimer légèrement
    une montée, jamais de créer une VAM impossible."""
    alt = np.asarray(altitude, dtype=float)
    if alt.size < 2:
        return alt
    da = np.diff(alt)
    dt = np.diff(np.asarray(t_at, dtype=float))
    jump = (da > 0) & (da > MAX_VERTICAL_MPS * np.maximum(dt, 0))
    return np.concatenate([[alt[0]], alt[0] + np.cumsum(np.where(jump, 0.0, da))])


def best_climb_for_gain(t_at, altitude, gain_m, dip=CLIMB_DIP_M) -> tuple[float, float] | None:
    """(temps le plus court en s, départ en s) pour s'élever de gain_m mètres à l'intérieur d'une
    même montée, ou None. L'altitude atteinte est le plus haut point déjà passé (un replat ou une
    petite descente ne fait pas reculer)."""
    alt = np.asarray(altitude, dtype=float)
    t_at = np.asarray(t_at, dtype=float)
    pts = turning_points(alt, dip)
    best = None
    for a, b in zip(pts, pts[1:], strict=False):
        if alt[b] - alt[a] < gain_m:
            continue
        seg_t, seg = t_at[a:b + 1], alt[a:b + 1]
        reached = np.maximum.accumulate(seg)
        target = seg + gain_m
        j = np.searchsorted(reached, target, side="left")
        i = np.nonzero(j < seg.size)[0]
        if not i.size:
            continue
        j = j[i]
        r0, r1 = reached[j - 1], reached[j]
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(r1 > r0, (target[i] - r0) / (r1 - r0), 0.0)
        times = seg_t[j - 1] + frac * (seg_t[j] - seg_t[j - 1]) - seg_t[i]
        k = int(np.argmin(times))
        if times[k] > 0 and (best is None or times[k] < best[0]):
            best = (float(times[k]), float(seg_t[i[k]]))
    return best


def window_avg_hr(t, hr, start_s, duration_s) -> float | None:
    """FC moyenne (pondérée par le temps) entre start_s et start_s + duration_s, ou None si la FC
    couvre moins de 80 % de la fenêtre."""
    if hr is None or duration_s <= 0:
        return None
    t = np.asarray(t, dtype=float)
    hr = np.asarray(hr, dtype=float)
    ok = np.isfinite(t) & np.isfinite(hr) & (hr > 0)
    t, hr = t[ok], hr[ok]
    end = start_s + duration_s
    if t.size < 2 or t[0] > start_s + 0.2 * duration_s or t[-1] < end - 0.2 * duration_s:
        return None
    area = np.concatenate([[0.0], np.cumsum(np.diff(t) * (hr[1:] + hr[:-1]) / 2)])
    lo, hi = max(start_s, t[0]), min(end, t[-1])
    return float((np.interp(hi, t, area) - np.interp(lo, t, area)) / (hi - lo)) if hi > lo else None


def activity_bests(t, distance, profile_distance=None, profile_altitude=None, hr=None) -> list[dict]:
    """Tous les meilleurs efforts d'une sortie : lignes (kind, key, value, start_s, extra, avg_hr)."""
    raw_t, raw_d = np.asarray(t, dtype=float), np.asarray(distance, dtype=float)
    t, d = clean_distance(t, distance)
    rows = []
    for dist in DISTANCES_M:
        best = best_time_for_distance(t, d, dist)
        if best:
            rows.append({"kind": "distance", "key": dist, "value": best[0], "start_s": best[1],
                         "extra": None, "avg_hr": window_avg_hr(raw_t, hr, best[1], best[0])})
    for dur in DURATIONS_S:
        meters = best_distance_for_duration(t, d, dur)
        if meters:
            rows.append({"kind": "duration", "key": dur, "value": meters, "start_s": None, "extra": None,
                         "avg_hr": None})
    if profile_distance is not None and len(profile_distance) > 1 and d.size > 1:
        # le profil d'altitude suit la distance brute de la série : le temps s'y lit sur la même échelle
        ok = np.isfinite(raw_t) & np.isfinite(raw_d)
        t_at = np.interp(profile_distance, np.maximum.accumulate(raw_d[ok]), raw_t[ok])
        profile_altitude = clean_altitude(t_at, profile_altitude)
        best = max(climbs(t_at, profile_altitude), key=lambda c: c["vam_mh"], default=None)
        if best:
            rows.append({"kind": "climb", "key": 0, "value": best["vam_mh"], "start_s": best["start_s"],
                         "extra": best["gain_m"],
                         "avg_hr": window_avg_hr(raw_t, hr, best["start_s"], best["duration_s"])})
        for gain in CLIMB_GAINS_M:
            found = best_climb_for_gain(t_at, profile_altitude, gain)
            if found:
                rows.append({"kind": "climb", "key": gain, "value": gain / found[0] * 3600,
                             "start_s": found[1], "extra": float(gain),
                             "avg_hr": window_avg_hr(raw_t, hr, found[1], found[0])})
    return rows
