"""
Estimateur de course (phase 3, fonctions pures, versionnées).

Forme actuelle : profil calculé sur les 6 à 12 dernières semaines (12 par défaut, réglable sur la
page) au soir du jour donné (les sorties
de ce jour comprises), pour pouvoir être rejoué à n'importe quelle date (validation sur les
courses passées avec la forme de la veille) :

- courbe allure-durée récente : meilleure distance tenue sur chaque durée et meilleur temps sur
  chaque distance, route et trail séparés ;
- VAM : meilleure montée de plus de 200 m et meilleurs paliers de D+ ;
- allure en descente : temps en mouvement par tranche de pente (toutes les sorties, quel que soit
  l'effort), par bandes de pente ;
- fitness, fatigue et forme (modèle de Banister, comme la page Forme) ;
- Efficiency Factor des sorties faciles et plates, comparé aux 12 mois précédents.

Route : formule de Riegel, T2 = T1 × (D2 / D1)^k, avec l'exposant standard k = 1,06 (choix de
Greg après la validation : l'exposant personnel, calé sur la frontière des meilleurs efforts route
des 2 dernières années, donnait 8,4 % d'erreur contre 4,4 % ; il reste calculé pour comparaison).
Le niveau vient des meilleurs efforts route de la même période que la forme : chacun est extrapolé à la
distance visée et l'estimation la plus rapide est retenue (un effort d'entraînement n'est pas
toujours à fond).
Chaque référence est ramenée à ton aérobie du jour : son temps est multiplié par le rapport de ta
vitesse à FC 150 à sa date et au jour donné (droites FC / vitesse sur 12 mois, hr_speed.SpeedTrend).
Les références sont cherchées sur 4 mois (REFERENCE_DAYS), plus longtemps que la forme : une séance
rapide d'il y a 3 mois compte encore, ramenée à la forme du jour. Choix de Greg après le rejeu des
courses : erreur 4,6 % au lieu de 5,0 %, biais −0,9 % au lieu de +2,9 %, 15 sauts de plus de 5 % d'une
semaine à l'autre au lieu de 20 (12 semaines ajustées : 3,6 % mais aussi instable qu'avant).
Le D+ éventuel est converti en distance équivalente sur le plat (coût de Minetti d'une montée à
5 %, descente neutre). La fourchette s'élargit avec l'écart entre la distance de référence et la
distance visée (incertitude sur l'exposant).

Les constantes de la fourchette sont des hypothèses de départ, à confronter à l'erreur mesurée
sur les courses passées (étape de validation).
"""
import json
import math
from datetime import date, timedelta
from statistics import median

from . import grade, stats

PROFILE_VERSION = 1
ESTIMATE_VERSION = 3           # 2 : exposant standard ; 3 : références ajustées par la FC
WINDOW_DAYS = 84               # 12 semaines, par défaut
FORM_WEEKS = (6, 8, 10, 12)    # fenêtres de la forme actuelle proposées sur la page
EF_REFERENCE_DAYS = 365

DURATION_LABELS = stats.DURATION_LABELS
DISTANCE_LABELS = stats.DISTANCE_LABELS
CLIMB_LABELS = {0: "Montée > 200 m", 100: "100 m de D+", 200: "200 m de D+", 500: "500 m de D+",
                1000: "1 000 m de D+"}
# bandes de pente (en %, borne basse incluse, borne haute exclue) pour l'allure en descente,
# avec le plat comme repère
SLOPE_BANDS = [(-2, 2, "Plat (−2 à +2 %)"), (-10, -4, "Descente douce (−4 à −10 %)"),
               (-20, -10, "Descente (−10 à −20 %)"), (-46, -20, "Forte descente (plus de −20 %)")]
SLOPE_MIN_S = 300              # en dessous de 5 min dans la bande, l'allure n'est pas affichée

RIEGEL_DEFAULT = 1.06          # exposant standard de Riegel
STANDARD_EXPONENT = {"value": RIEGEL_DEFAULT, "fitted": None, "personal": False, "n": 0, "bounded": False,
                     "range_km": None}
EXPONENT_BOUNDS = (1.02, 1.20)
EXPONENT_DAYS = 730
EXPONENT_MIN_RATIO = 3.0       # la frontière doit couvrir au moins un rapport 3 entre distances
MIN_REF_DISTANCE_M = 3000      # en dessous, effort trop court (part anaérobie)
MIN_REF_DURATION_S = 1200
REFERENCE_DAYS = 126           # références route cherchées sur 4 mois (choix de Greg), ajustées par la FC
# Réglages de l'estimateur (fenêtres, exposants, part d'arrêt, ajustement FC) choisis sur les courses
# de Greg jusqu'à cette date, puis figés : l'erreur mesurée sur ces courses-là est optimiste
# (surajustement) ; celle des courses suivantes est la vraie mesure.
TUNED_UNTIL = date(2026, 11, 3)
FALLBACK_WINDOW_DAYS = 182     # aucune référence route sur la période : on remonte à 6 mois
BASE_SPREAD = 0.02             # fourchette : ±2 %, plus 3 % par facteur e entre les distances
EXPONENT_SPREAD = 0.03
CLIMB_GRADE = 0.05
CLIMB_EQUIVALENT = (float(grade.minetti_cost(CLIMB_GRADE)) / grade.FLAT_COST - 1) / CLIMB_GRADE
STANDARD_DISTANCES_M = (5000, 10000, 21097.5, 42195)


def _in_window(day_iso: str, start: date, end: date) -> bool:
    return start.isoformat() <= day_iso[:10] <= end.isoformat()


def _effort(e) -> dict:
    return {"date": e["date"], "activity_id": e["id"], "name": e["name"]}


def _best(efforts, kind, key, lowest: bool):
    rows = [e for e in efforts if e["kind"] == kind and e["key"] == key]
    if not rows:
        return None
    return (min if lowest else max)(rows, key=lambda e: e["value"])


def pace_curve(efforts, terrain: str) -> dict:
    """Meilleurs efforts d'un terrain : distance tenue sur chaque durée, temps sur chaque distance."""
    rows = [e for e in efforts if e.get("terrain") == terrain]
    durations, distances = [], []
    for key, label in DURATION_LABELS.items():
        e = _best(rows, "duration", key, lowest=False)
        if e:
            durations.append({"key": key, "label": label, "distance_m": round(e["value"]),
                              "pace_s_km": round(key / e["value"] * 1000, 1), **_effort(e)})
    for key, label in DISTANCE_LABELS.items():
        e = _best(rows, "distance", key, lowest=True)
        if e:
            distances.append({"key": key, "label": label, "time_s": round(e["value"]),
                              "pace_s_km": round(e["value"] / key * 1000, 1), **_effort(e)})
    return {"durations": durations, "distances": distances}


def best_climbs(efforts) -> list[dict]:
    out = []
    for key, label in CLIMB_LABELS.items():
        e = _best(efforts, "climb", key, lowest=False)
        if e:
            out.append({"key": key, "label": label, "vam": round(e["value"]),
                        "gain_m": round(e["extra"] or 0),
                        "time_s": round((e["extra"] or 0) / e["value"] * 3600) if e["value"] else None,
                        **_effort(e)})
    return out


def slope_paces(acts) -> list[dict]:
    """Allure par bande de pente, toutes sorties confondues : temps et distance cumulés."""
    totals = {label: [0.0, 0.0, 0.0] for _, _, label in SLOPE_BANDS}     # secondes, mètres, dénivelé
    for a in acts:
        if not a.get("grade_bins"):
            continue
        for low, seconds, meters in json.loads(a["grade_bins"]):
            for lo, hi, label in SLOPE_BANDS:
                if lo <= low < hi:
                    t = totals[label]
                    t[0] += seconds
                    t[1] += meters
                    middle = low + grade.GRADE_BIN * 100 / 2          # pente au milieu de la tranche
                    t[2] += meters * abs(middle) / 100
    out = []
    for lo, hi, label in SLOPE_BANDS:
        seconds, meters, vertical = totals[label]
        enough = seconds >= SLOPE_MIN_S and meters > 0
        out.append({"label": label, "low": lo, "high": hi, "seconds": round(seconds),
                    "distance_m": round(meters),
                    "pace_s_km": round(seconds / meters * 1000, 1) if enough else None,
                    "vertical_mh": round(vertical / seconds * 3600) if enough and lo < -2 else None})
    return out


def _daily_load(acts) -> dict:
    daily = {}
    for a in acts:
        if a.get("hrss"):
            daily[a["start"].date()] = daily.get(a["start"].date(), 0.0) + a["hrss"]
    return daily


def current_form(acts, efforts, day: date, lthr: float, window_days: int = WINDOW_DAYS) -> dict:
    """Profil de forme au soir de `day`, sur les `window_days` jours qui se terminent ce jour-là."""
    start = day - timedelta(days=window_days - 1)
    recent = [a for a in acts if start <= a["start"].date() <= day]
    recent_efforts = [e for e in efforts if _in_window(e["date"], start, day)]

    daily = {d: v for d, v in _daily_load(acts).items() if d <= day}
    load = None
    if daily:
        cur = stats.banister(daily, min(daily), day)[-1]
        load = {"fitness": round(cur["fitness"], 1), "fatigue": round(cur["fatigue"], 1),
                "form": round(cur["form"], 1), "zone_label": stats.form_zone(cur["form"])[1]}

    ef_recent = [a["ef"] for a in recent if stats.is_easy_flat(a, lthr)]
    ref_start = start - timedelta(days=EF_REFERENCE_DAYS)
    ef_before = [a["ef"] for a in acts
                 if ref_start <= a["start"].date() < start and stats.is_easy_flat(a, lthr)]
    ef = None
    if ef_recent:
        now, before = median(ef_recent), median(ef_before) if ef_before else None
        ef = {"value": round(now, 3), "n": len(ef_recent),
              "reference": round(before, 3) if before else None,
              "delta_pct": round((now / before - 1) * 100, 1) if before else None}

    return {
        "version": PROFILE_VERSION,
        "day": day.isoformat(), "start": start.isoformat(), "window_days": window_days,
        "runs": len(recent),
        "distance_km": round(sum(a["distance_km"] for a in recent), 1),
        "hours": round(sum(a["moving_duration_s"] or 0 for a in recent) / 3600, 1),
        "gain_m": round(sum(a["gain_m"] for a in recent)),
        "road": pace_curve(recent_efforts, "road"),
        "trail": pace_curve(recent_efforts, "trail"),
        "climbs": best_climbs(recent_efforts),
        "slopes": slope_paces([a for a in recent if a.get("terrain") != "indoor"]),
        "load": load,
        "ef": ef,
    }


# ---------- route : Riegel à exposant personnel ----------

def road_points(efforts, start: date, end: date) -> list[dict]:
    """Efforts route utilisables comme référence (distance, temps) : distances d'au moins 3 km et
    durées d'au moins 20 min, le meilleur de chaque distance et de chaque durée sur la période."""
    best = {}
    for e in efforts:
        if e.get("terrain") != "road" or not _in_window(e["date"], start, end):
            continue
        if e["kind"] == "distance" and e["key"] >= MIN_REF_DISTANCE_M:
            point = {"distance_m": float(e["key"]), "time_s": float(e["value"])}
            label = DISTANCE_LABELS.get(e["key"], f"{e['key'] / 1000:g} km")
        elif e["kind"] == "duration" and e["key"] >= MIN_REF_DURATION_S:
            point = {"distance_m": float(e["value"]), "time_s": float(e["key"])}
            label = DURATION_LABELS.get(e["key"], f"{e['key'] / 60:g} min")
        else:
            continue
        k = (e["kind"], e["key"])
        if k not in best or point["time_s"] / point["distance_m"] < best[k]["time_s"] / best[k]["distance_m"]:
            best[k] = {**point, "kind": e["kind"], "label": label, **_effort(e)}
    return sorted(best.values(), key=lambda p: p["distance_m"])


def personal_exponent(efforts, day: date) -> dict:
    """Exposant de Riegel personnel : pente de log(temps) selon log(distance) sur la frontière des
    meilleurs efforts route des 2 dernières années, bornée ; exposant standard à défaut."""
    pts = road_points(efforts, day - timedelta(days=EXPONENT_DAYS - 1), day)
    if len(pts) >= 3 and pts[-1]["distance_m"] / pts[0]["distance_m"] >= EXPONENT_MIN_RATIO:
        xs = [math.log(p["distance_m"]) for p in pts]
        ys = [math.log(p["time_s"]) for p in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        k = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)
        low, high = EXPONENT_BOUNDS
        return {"value": round(min(high, max(low, k)), 3), "fitted": round(k, 3), "personal": True,
                "n": len(pts), "bounded": not low <= k <= high,
                "range_km": [round(pts[0]["distance_m"] / 1000, 1), round(pts[-1]["distance_m"] / 1000, 1)]}
    return {"value": RIEGEL_DEFAULT, "fitted": None, "personal": False, "n": len(pts), "bounded": False,
            "range_km": None}


def riegel(time_s: float, distance_m: float, target_m: float, exponent: float) -> float:
    return time_s * (target_m / distance_m) ** exponent


def equivalent_distance(distance_m: float, gain_m: float = 0.0) -> float:
    """Distance équivalente sur le plat : chaque mètre de D+ vaut CLIMB_EQUIVALENT mètres en plus."""
    return distance_m + max(0.0, gain_m) * CLIMB_EQUIVALENT


def predict_road(efforts, day: date, distance_m: float, gain_m: float = 0.0, exponent: dict | None = None,
                 window_days: int = WINDOW_DAYS, trend=None):
    """Temps estimé sur route « si je courais au soir de `day` », avec sa fourchette, ou None
    faute d'effort route récent. trend (hr_speed.SpeedTrend) : références ajustées à l'aérobie du
    jour ; la référence retenue porte alors son temps ajusté (time_s), le temps réel (raw_time_s)
    et l'ajustement (adjust_pct)."""
    exponent = exponent or STANDARD_EXPONENT
    window = max(window_days, REFERENCE_DAYS)
    refs = road_points(efforts, day - timedelta(days=window - 1), day)
    if not refs:
        window = FALLBACK_WINDOW_DAYS
        refs = road_points(efforts, day - timedelta(days=window - 1), day)
    if not refs or distance_m <= 0:
        return None
    k = exponent["value"]
    target = equivalent_distance(distance_m, gain_m)
    for r in refs:
        factor = trend.ratio(date.fromisoformat(r["date"][:10]), day) if trend else 1.0
        r["raw_time_s"] = r["time_s"]
        r["time_s"] = r["time_s"] * factor
        r["adjust_pct"] = round((factor - 1) * 100, 1) + 0.0
        r["predicted_s"] = round(riegel(r["time_s"], r["distance_m"], target, k))
    best = min(refs, key=lambda r: r["predicted_s"])
    time_s = riegel(best["time_s"], best["distance_m"], target, k)
    spread = BASE_SPREAD + EXPONENT_SPREAD * abs(math.log(target / best["distance_m"]))
    times = {"optimistic": time_s * math.exp(-spread), "realistic": time_s,
             "prudent": time_s * math.exp(spread)}
    return {
        "version": ESTIMATE_VERSION,
        "distance_m": distance_m, "gain_m": gain_m, "equivalent_m": round(target),
        **{f"{k_}_s": round(v) for k_, v in times.items()},
        **{f"{k_}_pace_s_km": round(v / distance_m * 1000, 1) for k_, v in times.items()},
        "spread_pct": round(spread * 100, 1),
        "reference": best, "references": refs,
        "exponent": exponent, "window_days": window, "fallback": window == FALLBACK_WINDOW_DAYS,
    }


def road_table(efforts, day: date, window_days: int = WINDOW_DAYS, trend=None) -> list[dict]:
    """Estimations sur les distances usuelles (5 km, 10 km, semi, marathon)."""
    out = []
    for d in STANDARD_DISTANCES_M:
        p = predict_road(efforts, day, d, window_days=window_days, trend=trend)
        if p:
            out.append({"label": DISTANCE_LABELS[d], **p})
    return out


# ---------- validation sur les courses passées ----------

def split_summary(rows, key) -> dict:
    """Erreur sur les courses ayant servi au réglage (jusqu'à TUNED_UNTIL) et sur les suivantes."""
    tuned = [r for r in rows if r["date"] <= TUNED_UNTIL.isoformat()]
    fresh = [r for r in rows if r["date"] > TUNED_UNTIL.isoformat()]
    return {"tuned": error_summary(tuned, key), "fresh": error_summary(fresh, key),
            "tuned_until": TUNED_UNTIL.isoformat()}


def error_summary(rows, key) -> dict | None:
    errors = [r[key] for r in rows if r.get(key) is not None]
    if not errors:
        return None
    return {"n": len(errors), "mae_pct": round(sum(abs(e) for e in errors) / len(errors), 1),
            "bias_pct": round(sum(errors) / len(errors), 1) + 0.0}     # + 0.0 : pas de « −0,0 »


def validate_road(acts, efforts, confirmed_ids, window_days: int = WINDOW_DAYS, trend=None) -> dict:
    """Estimateur route rejoué sur chaque course route confirmée, avec la forme de la veille :
    écart entre le temps estimé (réaliste) et le temps réel (écoulé), en %, positif quand
    l'estimation est trop lente. Comparé à l'exposant personnel."""
    rows = []
    for a in acts:
        if a["id"] not in confirmed_ids or a.get("terrain") != "road" or not a.get("distance_m"):
            continue
        actual = a.get("elapsed_s") or a["duration_s"]
        day = a["start"].date() - timedelta(days=1)
        used = predict_road(efforts, day, a["distance_m"], a["gain_m"], window_days=window_days, trend=trend)
        personal = predict_road(efforts, day, a["distance_m"], a["gain_m"],
                                exponent=personal_exponent(efforts, day), window_days=window_days,
                                trend=trend)
        row = {"activity_id": a["id"], "date": a["start"].date().isoformat(), "name": a["name"],
               "distance_km": round(a["distance_km"], 1), "gain_m": round(a["gain_m"]),
               "actual_s": round(actual), "estimate": None, "error_pct": None, "within": None,
               "personal_s": None, "personal_error_pct": None, "personal_k": None}
        if used:
            row.update({"estimate": used,
                        "error_pct": round((used["realistic_s"] / actual - 1) * 100, 1),
                        "within": used["optimistic_s"] <= actual <= used["prudent_s"]})
        if personal:
            row.update({"personal_s": personal["realistic_s"], "personal_k": personal["exponent"]["value"],
                        "personal_error_pct": round((personal["realistic_s"] / actual - 1) * 100, 1)})
        rows.append(row)
    rows.sort(key=lambda r: r["date"], reverse=True)
    summary = error_summary(rows, "error_pct")
    if summary:
        summary["within"] = sum(1 for r in rows if r["within"])
    return {"version": ESTIMATE_VERSION, "races": rows, "used": summary,
            "personal": error_summary(rows, "personal_error_pct"), "split": split_summary(rows, "error_pct")}


# ---------- modèle allure-pente personnel ----------
#
# Pour chaque sortie, la vitesse dans chaque tranche de pente de 2 % est rapportée à la vitesse sur
# le plat (−2 à +2 %) de la même sortie : le rapport ne dépend pas de l'intensité de la sortie
# (footing ou séance), seulement de la pente. Facteur = temps sur la pente / temps sur le plat à
# distance égale (2 = deux fois plus lent). Ce n'est pas un effort strictement égal : c'est ta
# façon habituelle de courir les pentes (marche en forte montée, retenue en descente technique).
# Les facteurs de chaque sortie sont moyennés (moyenne géométrique pondérée par le temps passé
# dans la tranche, plafonné à 10 min par sortie), puis lissés sur les tranches voisines.
# Au-delà des tranches mesurées, le facteur de la dernière tranche est conservé.

MODEL_VERSION = 1
MODEL_DAYS = 365               # par défaut ; None = tout l'historique
MODEL_PERIODS = {6: 182, 12: 365, 24: 730, 0: None}      # mois proposés sur la page → jours
MODEL_FLAT_MIN_S = 300         # plat d'au moins 5 min dans la sortie pour servir de référence
MODEL_BIN_MIN_S = 60           # tranche d'au moins 1 min dans la sortie
MODEL_BIN_MAX_WEIGHT_S = 600
MODEL_MIN_ACTIVITIES = 3       # tranche retenue si au moins 3 sorties y contribuent
FLAT_BINS = (-2, 0)
MODEL_TABLE_GRADES = (-30, -20, -10, -5, 0, 5, 10, 20, 30)


def grade_pace_model(acts, day: date, days: int | None = MODEL_DAYS) -> dict | None:
    """Modèle allure-pente personnel sur les `days` jours qui se terminent au soir de `day` (tout
    l'historique si None), ou None."""
    start = day - timedelta(days=days - 1) if days else min((a["start"].date() for a in acts), default=day)
    sums = {}                       # tranche → [somme pondérée des log-facteurs, poids, sorties, secondes]
    flat_s = flat_m = 0.0
    used = 0
    for a in acts:
        if not a.get("grade_bins") or a.get("terrain") == "indoor" or not start <= a["start"].date() <= day:
            continue
        bins = {low: (seconds, meters) for low, seconds, meters in json.loads(a["grade_bins"])}
        fs = sum(bins.get(g, (0, 0))[0] for g in FLAT_BINS)
        fm = sum(bins.get(g, (0, 0))[1] for g in FLAT_BINS)
        if fs < MODEL_FLAT_MIN_S or fm <= 0:
            continue
        used += 1
        flat_s, flat_m = flat_s + fs, flat_m + fm
        flat_speed = fm / fs
        for low, (seconds, meters) in bins.items():
            if seconds < MODEL_BIN_MIN_S or meters <= 0:
                continue
            w = min(seconds, MODEL_BIN_MAX_WEIGHT_S)
            s = sums.setdefault(low, [0.0, 0.0, 0, 0.0])
            s[0] += w * math.log(flat_speed / (meters / seconds))
            s[1] += w
            s[2] += 1
            s[3] += seconds
    kept = sorted(low for low, s in sums.items() if s[2] >= MODEL_MIN_ACTIVITIES)
    if not kept or used == 0:
        return None
    raw = {low: sums[low][0] / sums[low][1] for low in kept}
    half = grade.GRADE_BIN * 100 / 2
    out = []
    for low in kept:
        # lissage : moyenne des tranches voisines (±2 %) pondérée par leur poids
        near = [n for n in (low - 2 * half, low, low + 2 * half) if n in raw]
        smooth = sum(raw[n] * sums[n][1] for n in near) / sum(sums[n][1] for n in near)
        center = low + half
        out.append({"grade": center, "factor": round(math.exp(smooth), 3),
                    "raw": round(math.exp(raw[low]), 3),
                    "minetti": round(float(grade.minetti_cost(center / 100)) / grade.FLAT_COST, 3),
                    "activities": sums[low][2], "seconds": round(sums[low][3])})
    return {"version": MODEL_VERSION, "day": day.isoformat(), "start": start.isoformat(),
            "activities": used, "flat_pace_s_km": round(flat_s / flat_m * 1000, 1), "bins": out}


def grade_factor(model: dict, grade_pct: float) -> float:
    """Facteur de temps du modèle pour une pente en % (interpolé entre les tranches, borné aux
    tranches mesurées)."""
    pts = model["bins"]
    if grade_pct <= pts[0]["grade"]:
        return pts[0]["factor"]
    if grade_pct >= pts[-1]["grade"]:
        return pts[-1]["factor"]
    for a, b in zip(pts, pts[1:], strict=False):
        if a["grade"] <= grade_pct <= b["grade"]:
            f = (grade_pct - a["grade"]) / (b["grade"] - a["grade"])
            return a["factor"] + f * (b["factor"] - a["factor"])
    return 1.0


def model_table(model: dict) -> list[dict]:
    """Facteurs du modèle et de Minetti sur quelques pentes, avec l'allure correspondante à ton
    allure habituelle sur le plat."""
    out = []
    for g in MODEL_TABLE_GRADES:
        f = grade_factor(model, g)
        m = float(grade.minetti_cost(g / 100)) / grade.FLAT_COST
        pace = model["flat_pace_s_km"] * f
        out.append({"grade": g, "factor": round(f, 2), "minetti": round(m, 2), "pace_s_km": round(pace, 1),
                    "minetti_pace_s_km": round(model["flat_pace_s_km"] * m, 1),
                    "vertical_mh": round(abs(g) / 100 * 1000 / pace * 3600) if g else None})
    return out


# ---------- courses proches et effet de la forme ----------
#
# Effet de la forme : sur tout l'historique jusqu'au jour donné, chaque semaine, ton niveau (le 10 km
# estimé par l'estimateur route sur la fenêtre de la forme) est mis en face de ta fitness du jour.
# La pente de log(temps) selon la fitness donne le % de temps gagné par point de fitness (sur
# l'historique de Greg : −0,8 % par point, stable d'une année à l'autre, de −0,45 à −1,1 %).

LEVEL_DISTANCE_M = 10000
FORM_MIN_WEEKS = 26            # au moins 26 semaines avec un niveau pour une pente personnelle
FORM_SLOPE_DEFAULT = -0.005    # faute d'historique : −0,5 % par point, valeur générique prudente
FORM_SLOPE_BOUNDS = (-0.02, 0.0)
FORM_STEPS = (-10, -5, 5, 10)  # écarts de fitness proposés le jour J
NEAREST_RACES = 3
NEAREST_GAIN_OFFSET_M = 100    # D+ comparé en rapport, décalé pour que 0 et 50 m restent proches


def _level_points(efforts) -> list[tuple[str, float]]:
    """(date, temps estimé sur 10 km) de chaque effort route utilisable comme référence : le niveau
    d'une semaine est le minimum sur sa fenêtre, comme dans predict_road."""
    out = []
    for e in efforts:
        if e.get("terrain") != "road":
            continue
        if e["kind"] == "distance" and e["key"] >= MIN_REF_DISTANCE_M:
            d, t = float(e["key"]), float(e["value"])
        elif e["kind"] == "duration" and e["key"] >= MIN_REF_DURATION_S and e["value"]:
            d, t = float(e["value"]), float(e["key"])
        else:
            continue
        out.append((e["date"][:10], riegel(t, d, LEVEL_DISTANCE_M, RIEGEL_DEFAULT)))
    return sorted(out)


def fitness_slope(acts, efforts, day: date, window_days: int = WINDOW_DAYS) -> dict:
    """Pente de log(niveau) selon la fitness, semaine par semaine jusqu'au soir de `day` (bornée ;
    FORM_SLOPE_DEFAULT faute de FORM_MIN_WEEKS semaines)."""
    levels = _level_points(efforts)
    daily = {d: v for d, v in _daily_load(acts).items() if d <= day}
    pts = []
    if levels and daily:
        fitness = {p["date"]: p["fitness"] for p in stats.banister(daily, min(daily), day)}
        first = date.fromisoformat(levels[0][0])
        d, lo, hi = day, len(levels), len(levels)
        while d >= first:
            start, end = (d - timedelta(days=window_days - 1)).isoformat(), d.isoformat()
            while hi > 0 and levels[hi - 1][0] > end:
                hi -= 1
            lo = min(lo, hi)
            while lo > 0 and levels[lo - 1][0] >= start:
                lo -= 1
            in_window = [t for iso, t in levels[lo:hi] if iso >= start]
            if in_window and d in fitness:
                pts.append((fitness[d], math.log(min(in_window))))
            d -= timedelta(days=7)
    if len(pts) >= FORM_MIN_WEEKS:
        mx = sum(x for x, _ in pts) / len(pts)
        my = sum(y for _, y in pts) / len(pts)
        sxx = sum((x - mx) ** 2 for x, _ in pts)
        if sxx > 0:
            b = sum((x - mx) * (y - my) for x, y in pts) / sxx
            low, high = FORM_SLOPE_BOUNDS
            return {"value": min(high, max(low, b)), "fitted": b, "personal": True, "weeks": len(pts)}
    return {"value": FORM_SLOPE_DEFAULT, "fitted": None, "personal": False, "weeks": len(pts)}


def form_scenarios(time_s: float, fitness: float | None, slope: dict) -> list[dict]:
    """Temps estimé si tu arrivais le jour J avec plus ou moins de fitness qu'aujourd'hui."""
    if fitness is None:
        return []
    out = []
    for step in FORM_STEPS:
        if fitness + step <= 0:
            continue
        t = time_s * math.exp(slope["value"] * step)
        out.append({"delta": step, "fitness": round(fitness + step, 1), "time_s": round(t),
                    "gain_s": round(t - time_s)})
    return out


def nearest_races(acts, race_ids, distance_m: float, gain_m: float, before: date | None = None,
                  n: int = NEAREST_RACES) -> list[dict]:
    """Tes courses confirmées les plus proches en distance et en D+ (écart en rapport sur chacun),
    avec leur temps, leur allure et ta fitness ce jour-là."""
    daily = _daily_load(acts)
    fitness = ({p["date"]: p["fitness"] for p in stats.banister(daily, min(daily), max(daily))}
               if daily else {})
    rows = []
    for a in acts:
        if a["id"] not in race_ids or not a.get("distance_m") or (before and a["start"].date() >= before):
            continue
        g = NEAREST_GAIN_OFFSET_M
        score = abs(math.log(a["distance_m"] / distance_m)) + abs(math.log((a["gain_m"] + g) / (gain_m + g)))
        elapsed = a.get("elapsed_s") or a["duration_s"]
        f = fitness.get(a["start"].date())
        rows.append({"activity_id": a["id"], "date": a["start"].date().isoformat(), "name": a["name"],
                     "terrain": a.get("terrain"), "distance_km": round(a["distance_km"], 1),
                     "gain_m": round(a["gain_m"]), "elapsed_s": round(elapsed),
                     "pace_s_km": round(elapsed / a["distance_km"], 1) if a["distance_km"] else None,
                     "fitness": round(f, 1) if f is not None else None, "score": score})
    rows.sort(key=lambda r: r["score"])
    return rows[:n]


# ---------- correction (calibration activée dans l'admin) ----------

TIME_KEYS = ("optimistic_s", "realistic_s", "prudent_s", "moving_s", "stops_s", "optimistic_pace_s_km",
             "realistic_pace_s_km", "prudent_pace_s_km", "time_s", "passage_s", "pace_s_km", "leg_s",
             "arrival_s", "arrival_optimistic_s", "arrival_prudent_s", "departure_s", "predicted_s")


def apply_correction(result: dict | None, factor: float) -> dict | None:
    """Estimation (route ou trail) dont toutes les durées sont multipliées par le facteur de
    correction : temps, allures, tronçons, ravitos, temps de passage du profil. Les références
    (efforts réels) restent telles quelles."""
    if not result or result.get("error") or factor == 1.0:
        return result

    def scale(d: dict) -> dict:
        return {k: (round(v * factor, 1) if k.endswith("pace_s_km") else round(v * factor))
                if k in TIME_KEYS and isinstance(v, int | float) else v for k, v in d.items()}

    out = scale(result)
    for key in ("segments", "aid_stations"):
        if key in out:
            out[key] = [scale(x) for x in out[key]]
    if "chart" in out:
        out["chart"] = {**out["chart"], "time": [round(t * factor) for t in out["chart"]["time"]]}
    out["correction"] = {"factor": factor, "pct": round((factor - 1) * 100, 1)}
    return out

