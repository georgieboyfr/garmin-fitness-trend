"""
Détection automatique des courses (fonctions pures).

Ni Garmin ni Strava ne marquent les courses : un score combine plusieurs indices, et au-delà
d'un seuil la sortie est proposée comme « course probable », à confirmer ou rejeter dans
l'admin. Chaque indice rapporte des points et une raison lisible :

- nom ou description (mots-clés modifiables dans l'admin) ;
- effort cardiaque élevé pour la durée (FC moyenne rapportée à la LTHR) ;
- charge par heure (HRSS/h) dans les 10 % les plus élevées ;
- distance ronde (5, 10, semi, marathon) courue à un effort soutenu ;
- allure nettement plus rapide que les sorties de distance et de terrain comparables ;
- record ou quasi-record (top 3) sur un segment ;
- départ loin des lieux habituels, le week-end en matinée, peu d'arrêts.

Ces indices sont des hypothèses de départ, à affiner sur les vraies courses.
"""
import math
import re
from statistics import median

DEFAULT_KEYWORDS = [
    "marathon", "semi", "trail du", "trail de", "trail des", "ultra", "10 km de", "10km de",
    "corrida", "cross", "course de", "dossard", "chrono", "épreuve", "foulées", "ekiden", "relais",
]
DEFAULT_THRESHOLD = 5
ROUND_DISTANCES_KM = (5.0, 10.0, 21.0975, 42.195)
ROUND_TOLERANCE = 0.03
FAR_FROM_HOME_KM = 25.0
HOME_RADIUS_KM = 3.0


def _haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def home_location(starts):
    """Lieu de départ le plus fréquent : le départ qui a le plus de voisins à moins de 3 km."""
    pts = [s for s in starts if s]
    if not pts:
        return None
    sample = pts[:: max(1, len(pts) // 300)]
    return max(sample, key=lambda p: sum(_haversine_km(p, q) < HOME_RADIUS_KM for q in pts))


def hr_ratio_threshold(hours: float) -> float:
    """FC moyenne / LTHR attendue à fond selon la durée (une heure à fond ~ la LTHR)."""
    if hours < 1.5:
        return 0.95
    if hours < 3:
        return 0.90
    if hours < 5:
        return 0.85
    return 0.80


def keyword_match(text: str, keywords) -> str | None:
    text = (text or "").lower()
    for k in keywords:
        k = k.strip().lower()
        if k and re.search(r"(?<![\w])" + re.escape(k) + r"(?![\w])", text):
            return k
    return None


def build_context(acts, efforts, lthr, keywords):
    """Repères communs à toutes les sorties : lieu habituel, charge par heure, allures habituelles,
    sorties détenant un top 3 sur un segment."""
    hrss_per_h = sorted(a["hrss"] / (a["moving_duration_s"] / 3600) for a in acts
                        if a.get("hrss") and (a["moving_duration_s"] or 0) > 600)
    p90 = hrss_per_h[int(0.9 * (len(hrss_per_h) - 1))] if hrss_per_h else None
    top3 = set()
    by_key = {}
    for e in efforts:
        if e["kind"] == "distance":
            by_key.setdefault((e["key"], e["terrain"]), []).append(e)
    for rows in by_key.values():
        top3.update(e["id"] for e in sorted(rows, key=lambda e: e["value"])[:3])
    return {"lthr": lthr, "keywords": keywords, "hrss_per_h_p90": p90, "top3": top3,
            "home": home_location([a.get("start_pos") for a in acts]), "acts": acts}


def usual_pace(a, acts):
    """Allure médiane des autres sorties de même terrain et de distance comparable (±30 %)."""
    km = a["distance_km"]
    paces = [x["moving_duration_s"] / x["distance_km"] for x in acts
             if x["id"] != a["id"] and x.get("terrain") == a.get("terrain") and x["distance_km"] > 1
             and x["moving_duration_s"] and abs(x["distance_km"] - km) <= 0.3 * km]
    return median(paces) if len(paces) >= 5 else None


def score(a, ctx) -> tuple[int, list[str]]:
    """Score de « course probable » et raisons."""
    points, reasons = 0, []
    km = a["distance_km"]
    moving = a["moving_duration_s"] or 0
    hours = moving / 3600

    k = keyword_match(f"{a.get('name') or ''} {a.get('description') or ''}", ctx["keywords"])
    if k:
        points += 3
        reasons.append(f"nom : « {k} »")

    effort = False
    if a.get("avg_hr") and ctx["lthr"] and moving > 900:
        ratio = a["avg_hr"] / ctx["lthr"]
        if ratio >= hr_ratio_threshold(hours):
            effort = True
            points += 2
            reasons.append(f"FC moyenne {round(ratio * 100)} % de la LTHR sur {hours:.1f} h"
                           .replace(".", ","))

    if ctx["hrss_per_h_p90"] and a.get("hrss") and moving > 600:
        if a["hrss"] / hours >= ctx["hrss_per_h_p90"]:
            points += 1
            reasons.append("charge par heure dans tes 10 % les plus élevées")

    for target in ROUND_DISTANCES_KM:
        if abs(km - target) <= ROUND_TOLERANCE * target and effort:
            points += 2
            reasons.append(f"distance ronde ({km:.1f} km) à effort soutenu".replace(".", ","))
            break

    usual = usual_pace(a, ctx["acts"]) if km > 1 and moving else None
    if usual and moving / km <= 0.92 * usual:
        points += 2
        reasons.append(f"allure {round((1 - moving / km / usual) * 100)} % plus rapide que d'habitude")

    if a["id"] in ctx["top3"]:
        points += 2
        reasons.append("top 3 de tes temps sur une distance")

    if ctx["home"] and a.get("start_pos") and _haversine_km(ctx["home"], a["start_pos"]) >= FAR_FROM_HOME_KM:
        points += 1
        reasons.append("départ loin de tes lieux habituels")

    start = a["start"]
    if start.weekday() >= 5 and 6 <= start.hour < 11:
        points += 1
        reasons.append("week-end en matinée")

    elapsed = a.get("elapsed_s") or 0
    if a.get("terrain") == "road" and elapsed > 1200 and moving and (elapsed - moving) / elapsed < 0.02:
        points += 1
        reasons.append("pratiquement sans arrêt")

    return points, reasons


def candidates(acts, efforts, lthr, keywords, threshold) -> list[dict]:
    """Sorties dont le score atteint le seuil, de la plus récente à la plus ancienne."""
    ctx = build_context(acts, efforts, lthr, keywords)
    out = []
    for a in acts:
        s, reasons = score(a, ctx)
        if s >= threshold:
            out.append({"id": a["id"], "score": s, "reasons": reasons})
    return out
