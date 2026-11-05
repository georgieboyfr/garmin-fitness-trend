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
from datetime import date, timedelta

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

TRAIL_VERSION = 4               # 2 : ravitos ; 3 : temps total ; 4 : références ajustées par la FC
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
STOP_POWER = 2                 # part d'arrêt ∝ (heures en mouvement)², voir stop_rate
STOP_DEFAULT = 0.001           # faute de course passée, valeur générique arrondie (non calée sur un
                               # coureur) : 0,9 % du temps total à 3 h, 3,6 % à 6 h, 10 % à 10 h
STOP_MAX_SHARE = 0.3


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
    return altitude_profile(dist, alt, source, params)


def altitude_profile(dist, alt, source: str, params: dict | None = None) -> dict | None:
    """Profil à partir d'une altitude brute tous les 10 m : filtre médian et D+ / D− avec les
    réglages de l'admin (seuil du baromètre pour une sortie qui en a un, du MNT sinon)."""
    params = params or settings.DEFAULTS["elevation"]
    if dist.size < 2 or dist[-1] - dist[0] < MIN_DISTANCE_M:
        return None
    threshold = params["threshold_barometer"] if source == "barometer" else params["threshold_dem"]
    alt = median_filter(alt, int(params["window"]))
    gain, loss = hysteresis_gain_loss(alt, threshold)
    return {"distance": dist - dist[0], "altitude": alt, "source": source, "gain_m": gain, "loss_m": loss,
            "threshold_m": threshold}


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
    seuil d'hystérésis que le total), temps en mouvement, allure, VAP (courbe de Strava) et passage
    (arrêts aux ravitos compris : stops = temps d'arrêt cumulé à chaque point du profil)."""
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
    # VAP : courbe de Strava, comme la fiche de sortie, sur un point tous les 100 m (au pas de 10 m,
    # les oscillations d'altitude du GPX gonflent la distance équivalente)
    step = max(1, int(CHART_STEP_M / STEP_M))
    pick = np.unique(np.concatenate([np.arange(0, d.size, step), [d.size - 1]]))
    eq = np.interp(d, d[pick], grade.equivalent_distance(d[pick], alt[pick]))
    for i, j, cls in merged:
        gain, loss = hysteresis_gain_loss(alt[i:j + 1], threshold)
        length = d[j] - d[i]
        seconds = times[j] - times[i]
        flat = eq[j] - eq[i]
        out.append({"start_km": round(d[i] / 1000, 2), "end_km": round(d[j] / 1000, 2),
                    "length_m": round(length), "gain_m": round(gain), "loss_m": round(loss),
                    "grade_pct": round(_fitted_grade(d, alt, i, j), 1),
                    "kind": "rolling" if cls == "rolling" else "flat" if cls == "flat" else cls[:-1],
                    "label": SEGMENT_LABELS[cls],
                    "time_s": round(seconds),
                    "passage_s": round(times[j] + (stops[j] if stops is not None else 0.0)),
                    "pace_s_km": round(seconds / length * 1000, 1) if length else None,
                    "gap_pace_s_km": round(seconds / flat * 1000, 1) if flat > 0 else None,
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


def stop_rate(acts, race_ids, day: date) -> dict:
    """Part d'arrêt en course selon la durée : part du temps total passée à l'arrêt = a × (heures en
    mouvement)², a calé par moindres carrés sur les courses trail confirmées jusqu'au soir de `day` ;
    STOP_DEFAULT faute de course. Le carré suit l'allongement des ravitos sur les longues courses
    (proportionnelle à la durée, la part donnait 9 % d'arrêt sur 5 h 30 pour 2 % réels). Les sorties
    d'entraînement ne servent pas : leurs pauses (20 à 25 % au-delà de 2 h) ne ressemblent pas aux
    arrêts d'une course."""
    pts = []
    for a in acts:
        moving, elapsed = a.get("moving_duration_s"), a.get("elapsed_s")
        if (a["id"] in race_ids and a.get("terrain") == "trail" and a["start"].date() <= day
                and moving and elapsed and elapsed >= moving):
            pts.append({"hours": moving / 3600, "share": (elapsed - moving) / elapsed,
                        "date": a["start"].date().isoformat(), "activity_id": a["id"], "name": a.get("name")})
    sxx = sum(p["hours"] ** (2 * STOP_POWER) for p in pts)
    points = [{**p, "hours": round(p["hours"], 2), "share_pct": round(p["share"] * 100, 1)} for p in pts]
    if sxx > 0:
        return {"a": sum(p["hours"] ** STOP_POWER * p["share"] for p in pts) / sxx, "personal": True,
                "points": points}
    return {"a": STOP_DEFAULT, "personal": False, "points": points}


def aid_table(profile, times, stations, spread: float, factor: float = 1.0) -> list[dict]:
    """Passage à chaque ravito puis à l'arrivée : depuis le point précédent (distance, D+, D−,
    temps en mouvement), arrivée (avec sa fourchette), arrêt et départ. factor : arrêts répartis
    au prorata du temps (part d'arrêt de l'historique), quand aucun arrêt n'est saisi."""
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
                    "leg_s": round(moving - prev_t), "arrival_s": round(moving * factor + stopped),
                    "arrival_optimistic_s": round(moving * math.exp(-spread) * factor + stopped),
                    "arrival_prudent_s": round(moving * math.exp(spread) * factor + stopped),
                    "stop_s": round(stop), "departure_s": round(moving * factor + stopped + stop),
                    "altitude_m": round(float(alt[i]))})
        prev_i, prev_m, prev_t, stopped = i, at, moving, stopped + stop
    return out


def model_coverage(profile, model) -> float:
    """Part de la distance (%) sur des pentes couvertes par les tranches du modèle allure-pente
    (au-delà, le facteur de la tranche extrême est prolongé)."""
    d = np.asarray(profile["distance"], dtype=float)
    if d.size < 2:
        return 100.0
    g = grade.smoothed_grade(d, profile["altitude"]) * 100
    step_g = (g[1:] + g[:-1]) / 2
    half = grade.GRADE_BIN * 100 / 2
    low, high = model["bins"][0]["grade"] - half, model["bins"][-1]["grade"] + half
    dd = np.diff(d)
    return round(float(dd[(step_g >= low) & (step_g <= high)].sum() / dd.sum() * 100), 1)


def predict_trail(profile, model, efforts, day: date, window_days: int = estimator.WINDOW_DAYS,
                  fatigue: dict | None = None, aid_stations=None, stops: dict | None = None,
                  trend=None) -> dict | None:
    """Temps estimé sur le parcours, avec sa fourchette, ses tronçons, ses ravitos et son profil,
    ou None faute de modèle allure-pente ou d'effort route récent. Les temps (`*_s`) sont des temps
    totaux : arrêts saisis aux ravitos s'il y en a, sinon part d'arrêt de l'historique (`stops`,
    voir stop_rate) ; les allures portent sur le temps en mouvement."""
    if not model:
        return None
    eq_cum = equivalent_steps(profile, model)
    eq_m = float(eq_cum[-1])
    road = estimator.predict_road(efforts, day, eq_m, window_days=window_days, trend=trend)
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
    planned_s = sum(a["stop_min"] * 60 for a in stations)
    estimates = {"optimistic": total * math.exp(-spread), "realistic": total,
                 "prudent": total * math.exp(spread)}
    factor, share = 1.0, None
    if planned_s > 0:
        source = "ravitos"
    elif stops:
        source = "history"
        share = min(stops["a"] * (total / 3600) ** STOP_POWER, STOP_MAX_SHARE)
        factor = 1 / (1 - share)
    else:
        source = None
    offsets = _stop_offsets(d, stations) + times * (factor - 1)
    totals = {k: v * factor + planned_s for k, v in estimates.items()}
    every = max(1, int(CHART_STEP_M / STEP_M))
    idx = np.unique(np.concatenate([np.arange(0, d.size, every), [d.size - 1]]))
    return {
        "version": TRAIL_VERSION,
        "distance_m": round(distance_m), "gain_m": round(profile.get("gain_m", 0.0)),
        "loss_m": round(profile.get("loss_m", 0.0)), "equivalent_m": round(eq_m),
        "elevation_source": profile.get("source", "gpx"),
        **{f"{k}_s": round(v) for k, v in totals.items()},
        **{f"{k}_pace_s_km": round(v / distance_m * 1000, 1) for k, v in estimates.items()},
        "moving_s": round(total), "stops_s": round(totals["realistic"] - total),
        "stops_source": source, "stop_share_pct": round(share * 100, 1) if share is not None else None,
        "stop_rate": stops,
        "spread_pct": round(spread * 100, 1),
        "reference": ref, "fatigue": fatigue, "fatigue_applies": d0 is not None,
        "window_days": road["window_days"], "fallback": road["fallback"],
        "model_coverage_pct": model_coverage(profile, model), "riegel_target_m": round(near),
        "segments": segments(profile, times, offsets),
        "aid_stations": aid_table(profile, times, stations, spread, factor),
        "chart": {"km": [round(float(d[i]) / 1000, 2) for i in idx],
                  "altitude": [round(float(alt[i])) for i in idx],
                  "time": [round(float(times[i] + offsets[i])) for i in idx],
                  "aid": [{"km": a["km"], "name": a["name"]} for a in stations]},
    }


def estimate_gpx(lats, lons, eles, acts, efforts, day: date, window_days=estimator.WINDOW_DAYS,
                 model_days=estimator.MODEL_DAYS, dem_profile=None, params=None, aid_stations=None,
                 race_ids=frozenset(), trend=None) -> dict:
    """Chaîne complète pour un GPX : profil, modèle allure-pente, fatigue et part d'arrêt (courses
    confirmées `race_ids`) au soir de `day`."""
    profile = route_profile(lats, lons, eles, dem_profile, params)
    if profile is None:
        return {"error": "Trace inutilisable : moins de 1 km, ou sans altitude sur plus de la moitié"
                         " des points."}
    model = estimator.grade_pace_model(acts, day, model_days)
    if not model:
        return {"error": "Pas assez de sorties avec un profil d'altitude pour ton modèle allure-pente."}
    result = predict_trail(profile, model, efforts, day, window_days,
                           fatigue_exponent(acts, model, day), aid_stations, stop_rate(acts, race_ids, day),
                           trend)
    if result is None:
        return {"error": "Aucun effort route de 3 km ou plus sur les 6 derniers mois pour caler le niveau."}
    return result




# ---------- validation sur les courses trail passées ----------

def validate_trail(races, acts, efforts, race_ids, window_days: int = estimator.WINDOW_DAYS,
                   model_days: int | None = estimator.MODEL_DAYS, trend=None) -> dict:
    """Estimateur trail rejoué sur chaque course trail confirmée, sa propre trace servant de GPX,
    avec la forme de la veille (sorties, modèle allure-pente, exposant de fatigue et part d'arrêt
    jusqu'à la veille). races : liste de (sortie, profil de sa trace ou None). Écart en %, positif
    quand l'estimation est trop lente : temps total estimé face au temps écoulé de la course (ce qui
    compte en course, arrêts compris) ; pour diagnostic, temps en mouvement estimé face au temps en
    mouvement."""
    rows = []
    for a, profile in races:
        day = a["start"].date() - timedelta(days=1)
        moving = a.get("moving_duration_s")
        elapsed = a.get("elapsed_s") or a.get("duration_s")
        row = {"activity_id": a["id"], "date": a["start"].date().isoformat(), "name": a["name"],
               "distance_km": round(a["distance_km"], 1), "gain_m": round(a["gain_m"]),
               "moving_s": round(moving) if moving else None,
               "elapsed_s": round(elapsed) if elapsed else None,
               "estimate": None, "error_pct": None, "moving_error_pct": None, "within": None,
               "reason": None}
        model = estimator.grade_pace_model(acts, day, model_days) if profile else None
        est = predict_trail(profile, model, efforts, day, window_days, fatigue_exponent(acts, model, day),
                            stops=stop_rate(acts, race_ids, day), trend=trend) if model else None
        if profile is None:
            row["reason"] = "trace ou altitude indisponible"
        elif model is None:
            row["reason"] = "pas de modèle allure-pente avant la course"
        elif est is None:
            row["reason"] = "pas d'effort route dans les 6 mois précédents"
        else:
            est = {k: v for k, v in est.items() if k not in ("segments", "chart", "aid_stations")}
            row["estimate"] = est
            if elapsed:
                row["error_pct"] = round((est["realistic_s"] / elapsed - 1) * 100, 1) + 0.0
                row["within"] = est["optimistic_s"] <= elapsed <= est["prudent_s"]
            if moving:
                row["moving_error_pct"] = round((est["moving_s"] / moving - 1) * 100, 1) + 0.0
        rows.append(row)
    rows.sort(key=lambda r: r["date"], reverse=True)
    summary = estimator.error_summary(rows, "error_pct")
    if summary:
        summary["within"] = sum(1 for r in rows if r["within"])
    return {"version": TRAIL_VERSION, "races": rows, "total": summary,
            "moving": estimator.error_summary(rows, "moving_error_pct"),
            "split": estimator.split_summary(rows, "error_pct")}
