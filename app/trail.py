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
5. Tronçons homogènes : le profil (un point tous les 50 m) est approché par une suite de pentes
   régulières, découpage optimal où chaque coupure doit réduire l'écart au profil d'au moins
   SEGMENT_PENALTY (m²) ; chaque tronçon est classé par sa pente (plat, douce, moyenne, forte), les
   tronçons voisins de même classe sont fusionnés ; une suite de petites bosses (tronçons de moins
   de 500 m, pas en forte pente, montées et descentes mêlées) ou un tronçon plat ou doux qui
   cumule au moins 20 m de montée et 20 m de descente est dit « vallonné ».

6. Ravitaillements : points saisis sur le parcours (km, nom, durée d'arrêt), proposés au départ
   d'après les waypoints du GPX proches de la trace. Le temps de chaque arrêt s'ajoute aux passages
   qui suivent et au temps final ; les tronçons gardent leur temps en mouvement et la fourchette ne
   porte que sur le temps en mouvement (les arrêts sont ceux que tu prévois).
"""
import json
import math
from datetime import date

import numpy as np

from . import estimator, grade, settings
from .elevation import (
    EARTH_RADIUS_M,
    cumulative_distance,
    hysteresis_gain_loss,
    median_filter,
    resample,
    resample_positions,
)

TRAIL_VERSION = 2               # 2 : ravitaillements et arrêts
STEP_M = 10.0
MIN_DISTANCE_M = 1000.0
MIN_ELEVATION_SHARE = 0.5      # au moins la moitié des points avec une altitude
MIN_DEM_SHARE = 0.9            # le MNT doit couvrir 90 % du parcours pour être retenu
SEGMENT_STEP_M = 50.0          # pas du profil pour le découpage
SEGMENT_PENALTY = 2000.0       # m² : gain minimal d'une coupure sur l'écart quadratique au profil
SEGMENT_MIN_POINTS = 3         # tronçon d'au moins 100 m
SEGMENT_MAX_POINTS = 120       # 6 km au plus avant fusion
FLAT_GRADE_PCT = 3.0           # « plat » sous 3 % de pente
GENTLE_GRADE_PCT = 8.0         # « douce » sous 8 %
STEEP_GRADE_PCT = 15.0         # « forte » à partir de 15 %
ROLLING_MIN_M = 20.0           # « vallonné » : au moins 20 m de montée et 20 m de descente
ROLLING_PIECE_M = 500.0        # bosses : tronçons de moins de 500 m
SEGMENT_LABELS = {"flat": "Plat", "rolling": "Vallonné", "up1": "Montée douce", "up2": "Montée",
                  "up3": "Forte montée", "down1": "Descente douce", "down2": "Descente",
                  "down3": "Forte descente"}
FATIGUE_START_S = 7200.0       # au-delà de 2 h, l'exposant de fatigue prend le relais de Riegel
FATIGUE_DEFAULT = 1.15
FATIGUE_BOUNDS = (1.06, 1.35)
FATIGUE_BUCKETS_H = (2, 3, 4, 5, 6, 8, 10, 14, 24, 48)
FATIGUE_MIN_POINTS = 3
FATIGUE_SPREAD = 0.05          # fourchette : +5 % par facteur e au-delà des 2 premières heures
CHART_STEP_M = 100.0
AID_SNAP_M = 200.0             # waypoint retenu comme ravito s'il est à moins de 200 m de la trace
AID_END_MARGIN_M = 300.0       # ni au départ ni à l'arrivée
AID_MAX = 50
AID_NAME_MAX = 60
AID_STOP_MAX_MIN = 120


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


def fit_segments(d, a, penalty=SEGMENT_PENALTY, min_points=SEGMENT_MIN_POINTS,
                 max_points=SEGMENT_MAX_POINTS) -> list[int]:
    """Indices des coupures (premier et dernier point compris) du découpage optimal de a(d) en
    droites : minimise la somme des écarts quadratiques + penalty par tronçon (programmation
    dynamique, tronçons de min_points à max_points points, qui partagent leurs extrémités)."""
    d = np.asarray(d, dtype=float)
    a = np.asarray(a, dtype=float)
    n = d.size
    if n <= min_points:
        return [0, n - 1]
    pre = [np.concatenate([[0.0], np.cumsum(v)]) for v in (d, a, d * d, d * a, a * a)]

    def sse(b, j):          # écart quadratique de la droite des moindres carrés sur les points b..j
        sx, sy, sxx, sxy, syy = (p[j + 1] - p[b] for p in pre)
        m = j - b + 1
        vx, cxy, vy = sxx - sx * sx / m, sxy - sx * sy / m, syy - sy * sy / m
        return vy - np.where(vx > 0, cxy * cxy / np.where(vx > 0, vx, 1.0), 0.0)

    cost = np.zeros(n)
    prev = np.zeros(n, dtype=int)
    for j in range(1, n):
        b = np.arange(max(0, j - max_points + 1), max(1, j - min_points + 2))
        c = cost[b] + sse(b, j) + penalty
        k = int(np.argmin(c))
        cost[j], prev[j] = c[k], b[k]
    cuts, j = [n - 1], n - 1
    while j > 0:
        j = int(prev[j])
        cuts.append(j)
    return sorted(set(cuts))


def _slope_class(grade_pct: float) -> str:
    g = abs(grade_pct)
    if g < FLAT_GRADE_PCT:
        return "flat"
    side = "up" if grade_pct > 0 else "down"
    return side + ("1" if g < GENTLE_GRADE_PCT else "3" if g >= STEEP_GRADE_PCT else "2")


def _fitted_grade(d, alt, i, j) -> float:
    """Pente (%) de la droite des moindres carrés entre les points i et j du profil."""
    x, y = d[i:j + 1], alt[i:j + 1]
    if x.size < 3 or x[-1] == x[0]:
        return (y[-1] - y[0]) / (x[-1] - x[0]) * 100 if x[-1] != x[0] else 0.0
    return float(np.polyfit(x, y, 1)[0] * 100)


def segments(profile, times, stops=None) -> list[dict]:
    """Tronçons homogènes par pente (plat, douce, moyenne, forte, vallonné), avec D+ et D− (même
    seuil d'hystérésis que le total), temps en mouvement, allure et passage (arrêts aux ravitos
    compris : stops = temps d'arrêt cumulé à chaque point du profil)."""
    d, alt = profile["distance"], profile["altitude"]
    threshold = profile.get("threshold_m", 0.0)
    every = max(1, int(SEGMENT_STEP_M / STEP_M))
    coarse = np.unique(np.concatenate([np.arange(0, d.size, every), [d.size - 1]]))
    cuts = [int(coarse[k]) for k in fit_segments(d[coarse], alt[coarse])]
    # classe de chaque tronçon, puis fusion des voisins de même classe
    parts = []
    for i, j in zip(cuts, cuts[1:], strict=False):
        cls = _slope_class(_fitted_grade(d, alt, i, j))
        if parts and parts[-1][2] == cls:
            parts[-1][1] = j
        else:
            parts.append([i, j, cls])
    # suites de petites bosses (courtes, pas en forte pente, montées et descentes mêlées) regroupées
    grouped, k = [], 0
    while k < len(parts):
        run = k
        while (run < len(parts) and d[parts[run][1]] - d[parts[run][0]] < ROLLING_PIECE_M
               and parts[run][2] not in ("up3", "down3")):
            run += 1
        sides = {parts[r][2][:2] for r in range(k, run)}
        if run - k >= 2 and {"up", "do"} <= sides:
            grouped.append([parts[k][0], parts[run - 1][1], "bumps"])
            k = run
        else:
            grouped.append(parts[k])
            k += 1
    # vallonné : plat, doux ou bosses, avec de vraies montées et descentes ; voisins fusionnés
    merged = []
    for i, j, cls in grouped:
        gain, loss = hysteresis_gain_loss(alt[i:j + 1], threshold)
        if cls in ("flat", "up1", "down1", "bumps") and min(gain, loss) >= ROLLING_MIN_M:
            cls = "rolling"
        elif cls == "bumps":
            cls = _slope_class(_fitted_grade(d, alt, i, j))
        if merged and merged[-1][2] == cls == "rolling":
            merged[-1][1] = j
        else:
            merged.append([i, j, cls])
    out = []
    for i, j, cls in merged:
        gain, loss = hysteresis_gain_loss(alt[i:j + 1], threshold)
        length = d[j] - d[i]
        seconds = times[j] - times[i]
        out.append({"start_km": round(d[i] / 1000, 2), "end_km": round(d[j] / 1000, 2),
                    "length_m": round(length), "gain_m": round(gain), "loss_m": round(loss),
                    "grade_pct": round(_fitted_grade(d, alt, i, j), 1),
                    "kind": "rolling" if cls == "rolling" else "flat" if cls == "flat" else cls[:-1],
                    "label": SEGMENT_LABELS[cls],
                    "time_s": round(seconds),
                    "passage_s": round(times[j] + (stops[j] if stops is not None else 0.0)),
                    "pace_s_km": round(seconds / length * 1000, 1) if length else None,
                    "altitude_m": round(float(alt[j]))})
    return out


def waypoint_stations(lats, lons, waypoints) -> list[dict]:
    """Ravitos proposés d'après les waypoints du GPX : ceux à moins de 200 m de la trace, hors
    départ et arrivée, placés au km du point de trace le plus proche, sans arrêt."""
    lat = np.asarray(lats, dtype=float)
    lon = np.asarray(lons, dtype=float)
    if lat.size < 2 or not waypoints:
        return []
    cum = cumulative_distance(lat, lon)
    out = []
    for wlat, wlon, name in waypoints:
        dy = np.radians(lat - wlat) * EARTH_RADIUS_M
        dx = np.radians(lon - wlon) * EARTH_RADIUS_M * math.cos(math.radians(wlat))
        i = int(np.argmin(dx * dx + dy * dy))
        inside = AID_END_MARGIN_M <= cum[i] <= cum[-1] - AID_END_MARGIN_M
        if inside and math.hypot(dx[i], dy[i]) <= AID_SNAP_M:
            out.append({"km": round(float(cum[i]) / 1000, 2), "name": (name or "Ravito")[:AID_NAME_MAX],
                        "stop_min": 0.0})
    return sorted(out, key=lambda a: a["km"])[:AID_MAX]


def clean_stations(raw) -> list[dict]:
    """Ravitos saisis sur la page, vérifiés et triés par km ; ValueError si la saisie est invalide."""
    if not isinstance(raw, list) or len(raw) > AID_MAX:
        raise ValueError(f"Liste de ravitos invalide ({AID_MAX} au plus).")
    out = []
    for r in raw:
        try:
            km, stop = float(r["km"]), float(r.get("stop_min") or 0)
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError("Chaque ravito doit avoir un km et une durée d'arrêt en minutes.") from None
        if not (math.isfinite(km) and km > 0) or not 0 <= stop <= AID_STOP_MAX_MIN:
            raise ValueError(f"Km positif et arrêt de 0 à {AID_STOP_MAX_MIN} min.")
        name = str(r.get("name") or "").strip()[:AID_NAME_MAX] or "Ravito"
        out.append({"km": round(km, 2), "name": name, "stop_min": round(stop, 1)})
    return sorted(out, key=lambda a: a["km"])


def _stop_offsets(d, stations) -> np.ndarray:
    """Temps d'arrêt cumulé (s) à chaque point du profil : arrêts des ravitos situés avant."""
    out = np.zeros(d.size)
    for a in stations:
        out[d > a["km"] * 1000] += a["stop_min"] * 60
    return out


def aid_table(profile, times, stations, spread: float) -> list[dict]:
    """Passage à chaque ravito puis à l'arrivée : depuis le point précédent (distance, D+, D−,
    temps en mouvement), arrivée (avec sa fourchette), arrêt et départ."""
    d, alt = profile["distance"], profile["altitude"]
    threshold = profile.get("threshold_m", 0.0)
    points = [*stations, {"km": round(float(d[-1]) / 1000, 2), "name": "Arrivée", "stop_min": 0.0,
                          "finish": True}]
    out, prev_i, prev_m, prev_t, stopped = [], 0, 0.0, 0.0, 0.0
    for a in points:
        at = min(a["km"] * 1000, float(d[-1]))
        i = min(int(np.searchsorted(d, at)), d.size - 1)
        moving = float(np.interp(at, d, times))
        gain, loss = hysteresis_gain_loss(alt[prev_i:i + 1], threshold) if i > prev_i else (0.0, 0.0)
        stop = a["stop_min"] * 60
        out.append({"km": a["km"], "name": a["name"], "finish": a.get("finish", False),
                    "leg_m": round(at - prev_m), "leg_gain_m": round(gain), "leg_loss_m": round(loss),
                    "leg_s": round(moving - prev_t), "arrival_s": round(moving + stopped),
                    "arrival_optimistic_s": round(moving * math.exp(-spread) + stopped),
                    "arrival_prudent_s": round(moving * math.exp(spread) + stopped),
                    "stop_s": round(stop), "departure_s": round(moving + stopped + stop),
                    "altitude_m": round(float(alt[i]))})
        prev_i, prev_m, prev_t, stopped = i, at, moving, stopped + stop
    return out


def predict_trail(profile, model, efforts, day: date, window_days: int = estimator.WINDOW_DAYS,
                  fatigue: dict | None = None, aid_stations=None) -> dict | None:
    """Temps estimé sur le parcours, avec sa fourchette, ses tronçons, ses ravitos et son profil,
    ou None faute de modèle allure-pente ou d'effort route récent. Les temps (`*_s`) comprennent
    les arrêts aux ravitos, les allures et la fourchette portent sur le temps en mouvement."""
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
    stations = [a for a in (aid_stations or []) if 0 < a["km"] * 1000 < distance_m]
    stops = _stop_offsets(d, stations)
    stops_s = sum(a["stop_min"] * 60 for a in stations)
    estimates = {"optimistic": total * math.exp(-spread), "realistic": total,
                 "prudent": total * math.exp(spread)}
    every = max(1, int(CHART_STEP_M / STEP_M))
    idx = np.unique(np.concatenate([np.arange(0, d.size, every), [d.size - 1]]))
    return {
        "version": TRAIL_VERSION,
        "distance_m": round(distance_m), "gain_m": round(profile.get("gain_m", 0.0)),
        "loss_m": round(profile.get("loss_m", 0.0)), "equivalent_m": round(eq_m),
        "elevation_source": profile.get("source", "gpx"),
        **{f"{k}_s": round(v + stops_s) for k, v in estimates.items()},
        **{f"{k}_pace_s_km": round(v / distance_m * 1000, 1) for k, v in estimates.items()},
        "moving_s": round(total), "stops_s": round(stops_s),
        "spread_pct": round(spread * 100, 1),
        "reference": ref, "fatigue": fatigue, "fatigue_applies": d0 is not None,
        "window_days": road["window_days"], "fallback": road["fallback"],
        "segments": segments(profile, times, stops),
        "aid_stations": aid_table(profile, times, stations, spread),
        "chart": {"km": [round(float(d[i]) / 1000, 2) for i in idx],
                  "altitude": [round(float(alt[i])) for i in idx],
                  "time": [round(float(times[i] + stops[i])) for i in idx],
                  "aid": [{"km": a["km"], "name": a["name"]} for a in stations]},
    }


def estimate_gpx(lats, lons, eles, acts, efforts, day: date, window_days=estimator.WINDOW_DAYS,
                 model_days=estimator.MODEL_DAYS, dem_profile=None, params=None, aid_stations=None) -> dict:
    """Chaîne complète pour un GPX : profil, modèle allure-pente et fatigue au soir de `day`."""
    profile = route_profile(lats, lons, eles, dem_profile, params)
    if profile is None:
        return {"error": "Trace inutilisable : moins de 1 km, ou sans altitude sur plus de la moitié"
                         " des points."}
    model = estimator.grade_pace_model(acts, day, model_days)
    if not model:
        return {"error": "Pas assez de sorties avec un profil d'altitude pour ton modèle allure-pente."}
    result = predict_trail(profile, model, efforts, day, window_days,
                           fatigue_exponent(acts, model, day), aid_stations)
    if result is None:
        return {"error": "Aucun effort route de 3 km ou plus sur les 6 derniers mois pour caler le niveau."}
    return result

