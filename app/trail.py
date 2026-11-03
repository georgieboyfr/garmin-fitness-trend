"""
Estimateur trail sur un GPX (phase 3, fonctions pures, versionnées).

1. Profil : la trace est rééchantillonnée tous les 10 m ; l'altitude vient du MNT (IGN en France,
   Copernicus ailleurs) le long de la trace, comme pour les sorties sans baromètre, et à défaut de
   celle du GPX (souvent bruitée). Elle est filtrée avec les réglages de D+ de l'admin (médiane,
   seuil d'hystérésis du MNT) ; la pente est lissée sur 50 m comme pour les sorties.
2. Distance équivalente plat : chaque pas de 10 m compte pour 10 m × le facteur de ton modèle
   allure-pente personnel à cette pente (estimator.grade_pace_model).
3. Temps total : Riegel avec l'exposant standard 1,06 depuis ton meilleur effort route récent
   (comme l'estimateur route) tant que la course dure moins de 2 h ; au-delà, la fatigue suit ton
   exposant de fatigue : pente de log(temps) selon log(distance équivalente) sur ta courbe
   allure-durée longue (meilleure vitesse équivalente de tes sorties par tranche de durée à
   partir de 2 h, toutes années confondues jusqu'au jour donné).
4. Temps de passage : allure régulière (à pente égale) pendant les 2 premières heures, puis
   ralentissement progressif proportionnel à t^((k−1)/k), qui prolonge l'exposant de fatigue k
   sans saut d'allure ; la somme retombe exactement sur le temps total.
5. Tronçons homogènes : la trace est coupée à chaque sommet et à chaque creux (variation d'au moins
   25 m), soit une alternance de montées et de descentes.

Temps en mouvement : les arrêts aux ravitaillements ne sont pas comptés (étape suivante).
"""
import json
import math
from datetime import date

import numpy as np

from . import estimator, grade, settings
from .bests import turning_points
from .elevation import cumulative_distance, hysteresis_gain_loss, median_filter, resample, resample_positions

TRAIL_VERSION = 1
STEP_M = 10.0
MIN_DISTANCE_M = 1000.0
MIN_ELEVATION_SHARE = 0.5      # au moins la moitié des points avec une altitude
MIN_DEM_SHARE = 0.9            # le MNT doit couvrir 90 % du parcours pour être retenu
SEGMENT_DIP_M = 25.0
FLAT_GRADE_PCT = 3.0           # tronçon « plat » sous 3 % de pente moyenne
FATIGUE_START_S = 7200.0       # au-delà de 2 h, l'exposant de fatigue prend le relais de Riegel
FATIGUE_DEFAULT = 1.15
FATIGUE_BOUNDS = (1.06, 1.35)
FATIGUE_BUCKETS_H = (2, 3, 4, 5, 6, 8, 10, 14, 24, 48)
FATIGUE_MIN_POINTS = 3
FATIGUE_SPREAD = 0.05          # fourchette : +5 % par facteur e au-delà des 2 premières heures
CHART_STEP_M = 100.0


def dem_altitudes(dem, lats, lons) -> dict | None:
    """Altitude brute du MNT tous les 10 m le long de la trace, ou None (MNT injoignable ou
    couvrant moins de 90 % du parcours)."""
    lat = np.asarray(lats, dtype=float)
    lon = np.asarray(lons, dtype=float)
    if lat.size < 2:
        return None
    dist, la, lo = resample_positions(cumulative_distance(lat, lon), lat, lon, STEP_M)
    if dist.size < 2:
        return None
    try:
        alt, provider = dem.elevations(la, lo)
    except Exception:
        return None
    ok = np.isfinite(alt)
    if ok.mean() < MIN_DEM_SHARE:
        return None
    return {"distance": dist[ok], "altitude": np.asarray(alt, dtype=float)[ok], "source": provider}


def route_profile(lats, lons, eles, dem_profile: dict | None = None,
                  params: dict | None = None) -> dict | None:
    """Profil du parcours tous les 10 m (distance, altitude filtrée, D+ et D−, source de l'altitude),
    ou None si la trace est trop courte ou sans altitude. dem_profile : altitudes du MNT
    (dem_altitudes), prioritaires sur celles du GPX."""
    params = params or settings.DEFAULTS["elevation"]
    if dem_profile is not None:
        dist, alt, source = dem_profile["distance"], dem_profile["altitude"], dem_profile["source"]
    else:
        lat = np.asarray(lats, dtype=float)
        lon = np.asarray(lons, dtype=float)
        ele = np.array([np.nan if e is None else e for e in eles], dtype=float)
        if lat.size < 2 or np.isfinite(ele).mean() < MIN_ELEVATION_SHARE:
            return None
        dist, alt = resample(cumulative_distance(lat, lon), ele, STEP_M)
        source = "gpx"
    if dist.size < 2 or dist[-1] - dist[0] < MIN_DISTANCE_M:
        return None
    alt = median_filter(alt, int(params["window"]))
    gain, loss = hysteresis_gain_loss(alt, params["threshold_dem"])
    return {"distance": dist - dist[0], "altitude": alt, "source": source, "gain_m": gain, "loss_m": loss,
            "threshold_m": params["threshold_dem"]}


def equivalent_steps(profile, model) -> np.ndarray:
    """Distance équivalente plat cumulée à chaque point du profil (m), selon le modèle allure-pente."""
    d, alt = profile["distance"], profile["altitude"]
    g = grade.smoothed_grade(d, alt) * 100
    step_grade = (g[1:] + g[:-1]) / 2
    factors = np.interp(step_grade, [b["grade"] for b in model["bins"]], [b["factor"] for b in model["bins"]])
    return np.concatenate([[0.0], np.cumsum(np.diff(d) * factors)])


def activity_equivalent(a, model) -> tuple[float, float] | None:
    """(distance équivalente plat en m, temps en mouvement en s) d'une sortie, d'après ses tranches
    de pente."""
    if not a.get("grade_bins"):
        return None
    bins = json.loads(a["grade_bins"])
    half = grade.GRADE_BIN * 100 / 2
    meters = sum(m * estimator.grade_factor(model, low + half) for low, _, m in bins)
    seconds = sum(s for _, s, _ in bins)
    return (meters, seconds) if meters > 0 and seconds > 0 else None


def fatigue_exponent(acts, model, day: date) -> dict:
    """Exposant de fatigue : pente de log(temps) selon log(distance équivalente) sur la meilleure
    sortie de chaque tranche de durée à partir de 2 h, jusqu'au soir de `day`."""
    best = {}
    for a in acts:
        if a.get("terrain") == "indoor" or a["start"].date() > day:
            continue
        eq = activity_equivalent(a, model)
        if not eq:
            continue
        meters, seconds = eq
        hours = seconds / 3600
        for lo, hi in zip(FATIGUE_BUCKETS_H, FATIGUE_BUCKETS_H[1:], strict=False):
            if lo <= hours < hi and (lo not in best or meters / seconds > best[lo]["speed"]):
                best[lo] = {"speed": meters / seconds, "meters": meters, "seconds": seconds,
                            "date": a["start"].date().isoformat(), "activity_id": a["id"],
                            "name": a.get("name")}
    pts = [best[k] for k in sorted(best)]
    points = [{"hours": round(p["seconds"] / 3600, 1), "eq_km": round(p["meters"] / 1000, 1),
               "date": p["date"], "activity_id": p["activity_id"], "name": p["name"]} for p in pts]
    if len(pts) >= FATIGUE_MIN_POINTS:
        xs = [math.log(p["meters"]) for p in pts]
        ys = [math.log(p["seconds"]) for p in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            k = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
            low, high = FATIGUE_BOUNDS
            return {"value": round(min(high, max(low, k)), 3), "fitted": round(k, 3), "personal": True,
                    "points": points}
    return {"value": FATIGUE_DEFAULT, "fitted": None, "personal": False, "points": points}


def total_time(ref, eq_m: float, k_fatigue: float) -> tuple[float, float | None]:
    """(temps total en s, distance équivalente atteinte à 2 h ou None si la course dure moins)."""
    k = estimator.RIEGEL_DEFAULT
    t = estimator.riegel(ref["time_s"], ref["distance_m"], eq_m, k)
    if t <= FATIGUE_START_S:
        return t, None
    d0 = ref["distance_m"] * (FATIGUE_START_S / ref["time_s"]) ** (1 / k)
    return FATIGUE_START_S * (eq_m / d0) ** k_fatigue, d0


def passage_times(eq_cum, total_s: float, k_fatigue: float) -> np.ndarray:
    """Temps de passage (s) à chaque distance équivalente cumulée : allure régulière pendant
    2 h, puis allure proportionnelle à t^e avec e = (k − 1) / k ; total = total_s."""
    x = np.asarray(eq_cum, dtype=float)
    total_eq = x[-1]
    t0 = FATIGUE_START_S
    if total_s <= t0:
        return x / total_eq * total_s
    e = (k_fatigue - 1) / k_fatigue
    # dt/dx = c·max(t, t0)^e, résolu exactement ; c fixé pour finir à total_s
    a = 1 - e
    c = ((total_s ** a - t0 ** a) / a + t0 ** a) / total_eq
    x1 = t0 ** a / c                               # distance équivalente atteinte à 2 h
    phase1 = c * t0 ** e * x
    phase2 = np.maximum(t0 ** a + a * c * (x - x1), 0) ** (1 / a)
    return np.where(x <= x1, phase1, phase2)


def segments(profile, times) -> list[dict]:
    """Tronçons homogènes : montées et descentes entre sommets et creux successifs (D+ et D− de
    chaque tronçon avec le même seuil d'hystérésis que le total)."""
    d, alt = profile["distance"], profile["altitude"]
    threshold = profile.get("threshold_m", 0.0)
    cuts = sorted({0, len(d) - 1, *turning_points(alt, SEGMENT_DIP_M)})
    out = []
    for i, j in zip(cuts, cuts[1:], strict=False):
        if j <= i:
            continue
        gain, loss = hysteresis_gain_loss(alt[i:j + 1], threshold)
        length = d[j] - d[i]
        slope = (alt[j] - alt[i]) / length * 100 if length else 0.0
        seconds = times[j] - times[i]
        out.append({"start_km": round(d[i] / 1000, 2), "end_km": round(d[j] / 1000, 2),
                    "length_m": round(length), "gain_m": round(gain), "loss_m": round(loss),
                    "grade_pct": round(slope, 1),
                    "kind": "flat" if abs(slope) < FLAT_GRADE_PCT else ("up" if slope > 0 else "down"),
                    "time_s": round(seconds), "passage_s": round(times[j]),
                    "pace_s_km": round(seconds / length * 1000, 1) if length else None,
                    "altitude_m": round(float(alt[j]))})
    return out


def predict_trail(profile, model, efforts, day: date, window_days: int = estimator.WINDOW_DAYS,
                  fatigue: dict | None = None) -> dict | None:
    """Temps estimé sur le parcours, avec sa fourchette, ses tronçons et son profil, ou None
    faute de modèle allure-pente ou d'effort route récent."""
    if not model:
        return None
    eq_cum = equivalent_steps(profile, model)
    eq_m = float(eq_cum[-1])
    road = estimator.predict_road(efforts, day, eq_m, window_days=window_days)
    if not road:
        return None
    ref = road["reference"]
    fatigue = fatigue or {"value": FATIGUE_DEFAULT, "fitted": None, "personal": False, "points": []}
    total, d0 = total_time(ref, eq_m, fatigue["value"])
    near = d0 if d0 else eq_m
    spread = estimator.BASE_SPREAD + estimator.EXPONENT_SPREAD * abs(math.log(near / ref["distance_m"]))
    if d0:
        spread += FATIGUE_SPREAD * math.log(eq_m / d0)
    times = passage_times(eq_cum, total, fatigue["value"])
    d, alt = profile["distance"], profile["altitude"]
    distance_m = float(d[-1])
    estimates = {"optimistic": total * math.exp(-spread), "realistic": total,
                 "prudent": total * math.exp(spread)}
    every = max(1, int(CHART_STEP_M / STEP_M))
    idx = np.unique(np.concatenate([np.arange(0, d.size, every), [d.size - 1]]))
    return {
        "version": TRAIL_VERSION,
        "distance_m": round(distance_m), "gain_m": round(profile.get("gain_m", 0.0)),
        "loss_m": round(profile.get("loss_m", 0.0)), "equivalent_m": round(eq_m),
        "elevation_source": profile.get("source", "gpx"),
        **{f"{k}_s": round(v) for k, v in estimates.items()},
        **{f"{k}_pace_s_km": round(v / distance_m * 1000, 1) for k, v in estimates.items()},
        "spread_pct": round(spread * 100, 1),
        "reference": ref, "fatigue": fatigue, "fatigue_applies": d0 is not None,
        "window_days": road["window_days"], "fallback": road["fallback"],
        "segments": segments(profile, times),
        "chart": {"km": [round(float(d[i]) / 1000, 2) for i in idx],
                  "altitude": [round(float(alt[i])) for i in idx],
                  "time": [round(float(times[i])) for i in idx]},
    }


def estimate_gpx(lats, lons, eles, acts, efforts, day: date, window_days=estimator.WINDOW_DAYS,
                 model_days=estimator.MODEL_DAYS, dem_profile=None, params=None) -> dict:
    """Chaîne complète pour un GPX : profil, modèle allure-pente et fatigue au soir de `day`."""
    profile = route_profile(lats, lons, eles, dem_profile, params)
    if profile is None:
        return {"error": "Trace inutilisable : moins de 1 km, ou sans altitude sur plus de la moitié"
                         " des points."}
    model = estimator.grade_pace_model(acts, day, model_days)
    if not model:
        return {"error": "Pas assez de sorties avec un profil d'altitude pour ton modèle allure-pente."}
    result = predict_trail(profile, model, efforts, day, window_days,
                           fatigue_exponent(acts, model, day))
    if result is None:
        return {"error": "Aucun effort route de 3 km ou plus sur les 6 derniers mois pour caler le niveau."}
    return result

