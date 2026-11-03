"""
Métriques d'une sortie, calculées à partir de sa série de points (fonctions pures).

- Temps en mouvement : segments parcourus à au moins 0,5 m/s (marche en forte pente
  comprise), feux rouges et pauses exclus.
- TRIMP (Banister) et HRSS : charge cardiaque de la sortie ; 100 HRSS = 1 h à la LTHR.
- Temps par zone de FC, calées sur la LTHR (zones de course de Friel) :
  Z1 < 85 %, Z2 85–89 %, Z3 90–94 %, Z4 95–99 %, Z5 ≥ 100 % de la LTHR.
- Meilleures FC moyennes tenues 20, 30 et 60 min : servent à estimer la LTHR.
- Terrain : trail au-delà de 20 m de D+ par km, sinon route ; « indoor » sans GPS.
- Efficiency Factor (Friel) : vitesse en mouvement (m/min) / FC moyenne. S'il monte sur des
  sorties faciles et plates, tu cours plus vite pour le même effort cardiaque.
- Découplage cardiaque : baisse de l'EF entre la 1re et la 2e moitié du temps en mouvement,
  sur les sorties d'au moins 1 h. Sous 5 %, la base d'endurance tient sur cette durée.
"""
import math

import numpy as np

MOVING_SPEED_MPS = 0.5
MAX_SEGMENT_S = 60          # au-delà, le trou d'enregistrement n'est pas du mouvement
MAX_HR_GAP_S = 300          # TRIMP : pas d'intégration au-delà de 5 min sans FC
ZONE_BOUNDS = (0.85, 0.90, 0.95, 1.00)
TRAIL_GAIN_PER_KM = 20.0
HR_WINDOWS_S = {"hr_best_20min": 1200, "hr_best_30min": 1800, "hr_best_60min": 3600}
DECOUPLING_MIN_S = 3600


def _seconds(timestamps) -> np.ndarray:
    t = np.asarray(timestamps, dtype="datetime64[s]").astype(np.int64)
    return (t - t[0]).astype(float) if t.size else t.astype(float)


def moving_time(t, distance) -> float:
    """Temps en mouvement (s). t en secondes, distance cumulée en m (NaN tolérés)."""
    t = np.asarray(t, dtype=float)
    d = np.asarray(distance, dtype=float)
    ok = np.isfinite(d)
    t, d = t[ok], d[ok]
    if t.size < 2:
        return 0.0
    dt = np.diff(t)
    dd = np.diff(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        moving = (dt > 0) & (dt <= MAX_SEGMENT_S) & (dd / dt >= MOVING_SPEED_MPS)
    return float(dt[moving].sum())


def _hr_segments(t, hr, max_gap):
    """(durée, FC moyenne) de chaque segment entre deux points avec FC."""
    t = np.asarray(t, dtype=float)
    hr = np.asarray(hr, dtype=float)
    ok = np.isfinite(hr) & (hr > 0)
    t, hr = t[ok], hr[ok]
    if t.size < 2:
        return np.zeros(0), np.zeros(0)
    dt = np.diff(t)
    mid = (hr[:-1] + hr[1:]) / 2
    keep = (dt > 0) & (dt <= max_gap)
    return dt[keep], mid[keep]


def hr_reserve_ratio(hr, hr_rest, hr_max):
    return np.maximum(0.0, (np.asarray(hr, dtype=float) - hr_rest) / (hr_max - hr_rest))


def trimp(t, hr, hr_rest, hr_max, sex="m") -> float:
    """TRIMP de Banister : somme des minutes pondérées par la réserve de FC."""
    k = 1.92 if sex == "m" else 1.67
    dt, mid = _hr_segments(t, hr, MAX_HR_GAP_S)
    hrr = hr_reserve_ratio(mid, hr_rest, hr_max)
    return float(np.sum(dt / 60 * hrr * 0.64 * np.exp(k * hrr)))


def trimp_one_hour_at_lthr(hr_rest, hr_max, lthr, sex="m") -> float:
    k = 1.92 if sex == "m" else 1.67
    hrr = max(0.0, (lthr - hr_rest) / (hr_max - hr_rest))
    return 60 * hrr * 0.64 * math.exp(k * hrr)


def hrss(trimp_value, hr_rest, hr_max, lthr, sex="m") -> float:
    """HRSS : TRIMP rapporté à une heure à la LTHR (= 100)."""
    ref = trimp_one_hour_at_lthr(hr_rest, hr_max, lthr, sex)
    return trimp_value / ref * 100 if ref else 0.0


def zone_times(t, hr, lthr) -> list[float]:
    """Secondes passées dans chacune des 5 zones (Friel, en % de la LTHR)."""
    dt, mid = _hr_segments(t, hr, MAX_SEGMENT_S)
    idx = np.searchsorted(np.array(ZONE_BOUNDS) * lthr, mid, side="right")
    return [float(dt[idx == z].sum()) for z in range(5)]


def average_hr(t, hr) -> float | None:
    dt, mid = _hr_segments(t, hr, MAX_SEGMENT_S)
    return float(np.sum(dt * mid) / dt.sum()) if dt.sum() > 0 else None


def best_average_hr(t, hr, window_s: int, max_gap=30) -> float | None:
    """Meilleure FC moyenne tenue sur window_s secondes consécutives (grille d'une seconde,
    fenêtres traversant un trou de plus de max_gap secondes exclues)."""
    t = np.asarray(t, dtype=float)
    hr = np.asarray(hr, dtype=float)
    ok = np.isfinite(hr) & (hr > 0)
    t, hr = t[ok], hr[ok]
    if t.size < 2 or t[-1] - t[0] < window_s:
        return None
    grid = np.arange(t[0], t[-1] + 1)
    values = np.interp(grid, t, hr)
    # un point de grille est invalide s'il tombe dans un trou d'enregistrement
    gaps = np.diff(t) > max_gap
    invalid = np.zeros(grid.size, dtype=bool)
    for start, end in zip(t[:-1][gaps], t[1:][gaps], strict=True):
        invalid[int(start - t[0]) + 1:int(end - t[0])] = True
    cs = np.concatenate([[0.0], np.cumsum(values)])
    bad = np.concatenate([[0], np.cumsum(invalid)])
    w = int(window_s)
    sums = cs[w:] - cs[:-w]
    clean = (bad[w:] - bad[:-w]) == 0
    if not clean.any():
        return None
    return float((sums[clean] / w).max())


def _moving_hr_segments(t, distance, hr):
    """Segments en mouvement avec FC aux deux bouts : (durée s, distance m, FC moyenne)."""
    t = np.asarray(t, dtype=float)
    d = np.asarray(distance, dtype=float)
    hr = np.asarray(hr, dtype=float)
    ok = np.isfinite(d) & np.isfinite(hr) & (hr > 0)
    t, d, hr = t[ok], d[ok], hr[ok]
    if t.size < 2:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    dt, dd = np.diff(t), np.diff(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        moving = (dt > 0) & (dt <= MAX_SEGMENT_S) & (dd / dt >= MOVING_SPEED_MPS)
    return dt[moving], dd[moving], ((hr[:-1] + hr[1:]) / 2)[moving]


def _ef(dt, dd, hr):
    if dt.sum() <= 0:
        return None
    speed_m_min = dd.sum() / dt.sum() * 60
    avg_hr = np.sum(dt * hr) / dt.sum()
    return float(speed_m_min / avg_hr) if avg_hr > 0 else None


def efficiency_factor(t, distance, hr) -> float | None:
    return _ef(*_moving_hr_segments(t, distance, hr))


def decoupling(t, distance, hr) -> float | None:
    """Découplage (%) : (EF 1re moitié − EF 2e moitié) / EF 1re moitié, en temps de mouvement."""
    dt, dd, mid = _moving_hr_segments(t, distance, hr)
    if dt.sum() < DECOUPLING_MIN_S:
        return None
    first = np.cumsum(dt) <= dt.sum() / 2
    ef1, ef2 = _ef(dt[first], dd[first], mid[first]), _ef(dt[~first], dd[~first], mid[~first])
    return float((ef1 - ef2) / ef1 * 100) if ef1 and ef2 else None


def terrain(has_gps: bool, distance_km: float, gain_m: float) -> str:
    if not has_gps:
        return "indoor"
    if distance_km > 0 and gain_m / distance_km >= TRAIL_GAIN_PER_KM:
        return "trail"
    return "road"


def activity_metrics(table, gain_m, hr_rest, hr_max, lthr, sex="m") -> dict:
    """Toutes les métriques d'une sortie à partir de sa série (schéma fit_parser.SCHEMA)."""
    from .elevation import series_distance

    t = _seconds(table.column("timestamp").to_numpy(zero_copy_only=False))
    hr = table.column("heart_rate").to_numpy(zero_copy_only=False).astype(float)
    dist = series_distance(table)
    has_gps = table.column("lat").null_count < table.num_rows
    finite = dist[np.isfinite(dist)]
    distance_km = float(finite.max() - finite.min()) / 1000 if finite.size else 0.0
    tr = trimp(t, hr, hr_rest, hr_max, sex)
    has_hr = bool(np.isfinite(hr).any() and np.nanmax(hr) > 0)
    out = {
        "elapsed_s": float(t[-1]) if t.size else 0.0,
        "moving_s": moving_time(t, dist),
        "distance_km": distance_km,
        "avg_hr": average_hr(t, hr),
        "max_hr": float(np.nanmax(hr)) if has_hr else None,
        "trimp": tr if has_hr else None,
        "hrss": hrss(tr, hr_rest, hr_max, lthr, sex) if has_hr else None,
        "zones_s": zone_times(t, hr, lthr),
        "terrain": terrain(has_gps, distance_km, gain_m or 0.0),
        "ef": efficiency_factor(t, dist, hr) if has_hr else None,
        "decoupling_pct": decoupling(t, dist, hr) if has_hr else None,
    }
    for key, window in HR_WINDOWS_S.items():
        out[key] = best_average_hr(t, hr, window) if has_hr else None
    return out
