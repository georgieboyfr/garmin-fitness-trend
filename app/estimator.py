"""
Estimateur de course (phase 3, fonctions pures, versionnées).

Forme actuelle : profil calculé sur les 12 dernières semaines au soir du jour donné (les sorties
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
Le niveau vient des meilleurs efforts route des 12 dernières semaines : chacun est extrapolé à la
distance visée et l'estimation la plus rapide est retenue (un effort d'entraînement n'est pas
toujours à fond).
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
ESTIMATE_VERSION = 2           # 2 : exposant standard au lieu de l'exposant personnel
WINDOW_DAYS = 84               # 12 semaines
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
FALLBACK_WINDOW_DAYS = 182     # aucune référence route en 12 semaines : on remonte à 6 mois
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


def current_form(acts, efforts, day: date, lthr: float) -> dict:
    """Profil de forme au soir de `day`, sur les 12 semaines qui se terminent ce jour-là."""
    start = day - timedelta(days=WINDOW_DAYS - 1)
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
        "day": day.isoformat(), "start": start.isoformat(), "window_days": WINDOW_DAYS,
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


def predict_road(efforts, day: date, distance_m: float, gain_m: float = 0.0, exponent: dict | None = None):
    """Temps estimé sur route « si je courais au soir de `day` », avec sa fourchette, ou None
    faute d'effort route récent."""
    exponent = exponent or STANDARD_EXPONENT
    window = WINDOW_DAYS
    refs = road_points(efforts, day - timedelta(days=window - 1), day)
    if not refs:
        window = FALLBACK_WINDOW_DAYS
        refs = road_points(efforts, day - timedelta(days=window - 1), day)
    if not refs or distance_m <= 0:
        return None
    k = exponent["value"]
    target = equivalent_distance(distance_m, gain_m)
    for r in refs:
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
        "exponent": exponent, "window_days": window, "fallback": window != WINDOW_DAYS,
    }


def road_table(efforts, day: date) -> list[dict]:
    """Estimations sur les distances usuelles (5 km, 10 km, semi, marathon)."""
    out = []
    for d in STANDARD_DISTANCES_M:
        p = predict_road(efforts, day, d)
        if p:
            out.append({"label": DISTANCE_LABELS[d], **p})
    return out


# ---------- validation sur les courses passées ----------

def _error_summary(rows, key) -> dict | None:
    errors = [r[key] for r in rows if r.get(key) is not None]
    if not errors:
        return None
    return {"n": len(errors), "mae_pct": round(sum(abs(e) for e in errors) / len(errors), 1),
            "bias_pct": round(sum(errors) / len(errors), 1)}


def validate_road(acts, efforts, confirmed_ids) -> dict:
    """Estimateur route rejoué sur chaque course route confirmée, avec la forme de la veille :
    écart entre le temps estimé (réaliste) et le temps réel (écoulé), en %, positif quand
    l'estimation est trop lente. Comparé à l'exposant personnel."""
    rows = []
    for a in acts:
        if a["id"] not in confirmed_ids or a.get("terrain") != "road" or not a.get("distance_m"):
            continue
        actual = a.get("elapsed_s") or a["duration_s"]
        day = a["start"].date() - timedelta(days=1)
        used = predict_road(efforts, day, a["distance_m"], a["gain_m"])
        personal = predict_road(efforts, day, a["distance_m"], a["gain_m"],
                                exponent=personal_exponent(efforts, day))
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
    summary = _error_summary(rows, "error_pct")
    if summary:
        summary["within"] = sum(1 for r in rows if r["within"])
    return {"version": ESTIMATE_VERSION, "races": rows, "used": summary,
            "personal": _error_summary(rows, "personal_error_pct")}
