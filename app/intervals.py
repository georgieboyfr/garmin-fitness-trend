"""
Intervalles d'une séance (fonctions pures, plus la lecture des tours du FIT).

Deux sources, par ordre de préférence :
1. Les tours de la montre, s'ils décrivent la séance : entraînement structuré (tours marqués
   effort / récupération / échauffement / retour au calme) ou tours déclenchés à la main.
   Les tours automatiques (tous les km) ne décrivent pas une séance et sont ignorés.
2. Sinon, détection sur l'allure : la vitesse lissée se répartit en deux groupes (effort et
   récupération) nettement séparés, et au moins MIN_EFFORTS blocs rapides de durées
   comparables (une vraie séance répète le même effort ; un footing avec feux rouges ou
   côtes donne des blocs irréguliers). Les blocs isolés, deux fois plus courts ou plus
   longs que l'effort type, ne comptent pas. Réservé aux sorties sur route : en trail, la pente
   crée des changements d'allure qui ne sont pas des intervalles.
"""
from functools import lru_cache

import fitdecode
import numpy as np

STRUCTURED = {"active": "effort", "rest": "récupération", "recovery": "récupération",
              "warmup": "échauffement", "cooldown": "retour au calme"}
MIN_EFFORTS = 3
MIN_EFFORT_S = 40
MAX_EFFORT_S = 20 * 60
MERGE_GAP_S = 15
SMOOTH_S = 20
MIN_SPEED_GAP = 0.25        # écart minimal entre les vitesses d'effort et de récupération (25 %)
MAX_DURATION_CV = 0.35      # efforts réguliers : écart-type des durées sous 35 % de la moyenne
MAX_FAST_SHARE = 0.6        # les efforts ne couvrent pas l'essentiel de la sortie


def _field(frame, name):
    return frame.get_value(name, fallback=None) if frame.has_field(name) else None


@lru_cache(maxsize=64)
def _laps_cached(path: str, mtime: float) -> tuple:
    laps = []
    start0 = None
    with fitdecode.FitReader(path, check_crc=fitdecode.CrcCheck.DISABLED) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "session" and start0 is None and frame.has_field("start_time"):
                start0 = frame.get_value("start_time")
            if frame.name != "lap":
                continue
            def get(name, frame=frame):
                return _field(frame, name)

            laps.append({"start": get("start_time"),
                         "duration_s": get("total_timer_time") or get("total_elapsed_time"),
                         "distance_m": get("total_distance"), "avg_hr": get("avg_heart_rate"),
                         "max_hr": get("max_heart_rate"), "intensity": get("intensity"),
                         "trigger": get("lap_trigger")})
    return tuple(laps)


def read_laps(path) -> list[dict]:
    import os

    try:
        return list(_laps_cached(str(path), os.path.getmtime(path)))
    except (OSError, fitdecode.FitError):
        return []


def from_laps(laps) -> list[dict] | None:
    """Intervalles décrits par les tours de la montre, ou None s'ils ne décrivent pas la séance."""
    kinds = [STRUCTURED.get(lap["intensity"]) for lap in laps]
    structured = "effort" in kinds and "récupération" in kinds
    manual = sum(1 for lap in laps if lap["trigger"] == "manual") >= 3
    if not (structured or manual):
        return None
    rows = []
    start = 0.0
    for lap, kind in zip(laps, kinds, strict=True):
        if not lap["duration_s"]:
            continue
        rows.append({"kind": kind if structured else "tour", "start_s": start,
                     "duration_s": float(lap["duration_s"]),
                     "distance_m": float(lap["distance_m"] or 0), "avg_hr": lap["avg_hr"],
                     "max_hr": lap["max_hr"]})
        start += float(lap["duration_s"])
    return rows or None


def _two_means(values, iterations=20):
    lo, hi = np.percentile(values, 20), np.percentile(values, 80)
    for _ in range(iterations):
        mid = (lo + hi) / 2
        a, b = values[values < mid], values[values >= mid]
        if not a.size or not b.size:
            break
        lo, hi = a.mean(), b.mean()
    return lo, hi


def detect(t, distance, hr) -> list[dict] | None:
    """Intervalles détectés sur l'allure (temps t en s, distance cumulée en m, FC), ou None."""
    t = np.asarray(t, dtype=float)
    d = np.asarray(distance, dtype=float)
    ok = np.isfinite(t) & np.isfinite(d)
    t, d = t[ok], d[ok]
    if t.size < 60 or t[-1] - t[0] < 15 * 60:
        return None
    grid = np.arange(t[0], t[-1] + 1)
    dist = np.interp(grid, t, np.maximum.accumulate(d))
    speed = np.gradient(dist)
    kernel = np.ones(SMOOTH_S) / SMOOTH_S
    smooth = np.convolve(speed, kernel, mode="same")
    moving = smooth > 1.0
    if moving.sum() < 600:
        return None
    lo, hi = _two_means(smooth[moving])
    if lo <= 0 or (hi - lo) / lo < MIN_SPEED_GAP:
        return None
    fast = smooth >= (lo + hi) / 2

    # blocs rapides, petits trous rebouchés, blocs trop courts ou trop longs écartés
    edges = np.flatnonzero(np.diff(np.concatenate([[0], fast.astype(int), [0]])))
    blocks = [[int(a), int(b)] for a, b in zip(edges[::2], edges[1::2], strict=True)]
    merged = []
    for a, b in blocks:
        if merged and a - merged[-1][1] <= MERGE_GAP_S:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    efforts = [(a, b) for a, b in merged if MIN_EFFORT_S <= b - a <= MAX_EFFORT_S]
    if len(efforts) < MIN_EFFORTS:
        return None
    typical = float(np.median([b - a for a, b in efforts]))
    efforts = [(a, b) for a, b in efforts if 0.5 * typical <= b - a <= 2 * typical]
    durations = np.array([b - a for a, b in efforts], dtype=float)
    if (len(efforts) < MIN_EFFORTS or durations.std() / durations.mean() > MAX_DURATION_CV
            or durations.sum() > MAX_FAST_SHARE * moving.sum()):
        return None

    hr_grid = None
    hr = np.asarray(hr, dtype=float)[ok] if hr is not None else None
    if hr is not None and np.isfinite(hr).sum() > 10:
        good = np.isfinite(hr) & (hr > 0)
        hr_grid = np.interp(grid, t[good], hr[good])

    def row(kind, a, b):
        seg_hr = hr_grid[a:b] if hr_grid is not None else None
        return {"kind": kind, "start_s": float(a), "duration_s": float(b - a),
                "distance_m": float(dist[b - 1] - dist[a]),
                "avg_hr": round(float(seg_hr.mean())) if seg_hr is not None and seg_hr.size else None,
                "max_hr": round(float(seg_hr.max())) if seg_hr is not None and seg_hr.size else None}

    rows = []
    if efforts[0][0] > 30:
        rows.append(row("échauffement", 0, efforts[0][0]))
    for k, (a, b) in enumerate(efforts):
        rows.append(row("effort", a, b))
        if k + 1 < len(efforts):
            rows.append(row("récupération", b, efforts[k + 1][0]))
    if grid.size - efforts[-1][1] > 30:
        rows.append(row("retour au calme", efforts[-1][1], grid.size))
    return rows


def summary(rows) -> dict | None:
    efforts = [r for r in rows if r["kind"] == "effort"]
    if not efforts:
        return None
    dur = sum(r["duration_s"] for r in efforts)
    dist = sum(r["distance_m"] for r in efforts)
    return {"count": len(efforts), "mean_duration_s": dur / len(efforts),
            "mean_distance_m": dist / len(efforts), "pace_s_km": dur / dist * 1000 if dist else None}
