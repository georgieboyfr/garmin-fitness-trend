"""
Repères physiologiques estimés à partir des sorties (fonctions pures, versionnées) : VMA, VO2max,
FC et allure au seuil. Méthodes générales de la littérature, aucune constante calée sur un
coureur.

- VMA : vitesse du meilleur effort de 5 min sur route. La VMA se tient de 4 à 11 min, 6 en
  moyenne (Billat) ; un effort de 5 min à fond en donne donc une bonne estimation. Sous-estimée
  si aucun effort de 5 min n'a été couru à fond sur la période.
- VO2max : 3,5 ml/kg/min par km/h de VMA (Léger et Mercier, coût énergétique de la course).
- FC au seuil : meilleure FC moyenne tenue une heure sur 12 mois (une heure à fond se court au
  seuil), rapportée à la FC max.
- Allure au seuil : distance que l'estimateur donne en une heure (mêmes références route que les
  prédictions, ajustées à l'aérobie du jour, formule de Riegel).
"""
from datetime import date, timedelta

from . import estimator

PHYSIO_VERSION = 1
VMA_DURATION_S = 300
VO2_PER_KMH = 3.5
THRESHOLD_S = 3600.0


def vma(efforts, day: date) -> dict | None:
    """Meilleur effort route de 5 min sur la fenêtre de la forme, 6 mois à défaut."""
    for days in (estimator.WINDOW_DAYS, estimator.FALLBACK_WINDOW_DAYS):
        start = day - timedelta(days=days - 1)
        rows = [e for e in efforts if e.get("terrain") == "road" and e["kind"] == "duration"
                and e["key"] == VMA_DURATION_S and estimator._in_window(e["date"], start, day)]
        if rows:
            best = max(rows, key=lambda e: e["value"])
            kmh = best["value"] / VMA_DURATION_S * 3.6
            return {"kmh": round(kmh, 1), "pace_s_km": round(3600 / kmh, 1),
                    "vo2max": round(kmh * VO2_PER_KMH, 1), "window_days": days,
                    "fallback": days != estimator.WINDOW_DAYS, **estimator._effort(best)}
    return None


def threshold_pace(efforts, day: date, trend=None) -> dict | None:
    """Allure tenue une heure d'après le niveau de l'estimateur route."""
    window = estimator.REFERENCE_DAYS
    refs = estimator.road_points(efforts, day - timedelta(days=window - 1), day)
    if not refs:
        window = estimator.FALLBACK_WINDOW_DAYS
        refs = estimator.road_points(efforts, day - timedelta(days=window - 1), day)
    if not refs:
        return None
    k = estimator.RIEGEL_DEFAULT
    best, best_m = None, 0.0
    for r in refs:
        factor = trend.ratio(date.fromisoformat(r["date"][:10]), day) if trend else 1.0
        meters = r["distance_m"] * (THRESHOLD_S / (r["time_s"] * factor)) ** (1 / k)
        if meters > best_m:
            best, best_m = {**r, "adjust_pct": round((factor - 1) * 100, 1) + 0.0}, meters
    return {"distance_m": round(best_m), "pace_s_km": round(THRESHOLD_S / best_m * 1000, 1),
            "kmh": round(best_m / THRESHOLD_S * 3.6, 1), "reference": best, "fallback":
            window == estimator.FALLBACK_WINDOW_DAYS}


def threshold_hr(lthr_estimate: dict | None, hr_max: float | None) -> dict | None:
    """FC au seuil (meilleure FC moyenne tenue une heure) et sa part de la FC max."""
    best = (lthr_estimate or {}).get("best_60min")
    if not best:
        return None
    return {"hr": best["hr"], "pct_max": round(best["hr"] / hr_max * 100) if hr_max else None,
            "hr_max": round(hr_max) if hr_max else None, "date": best["date"],
            "activity_id": best["activity_id"]}


def physiology(efforts, day: date, lthr_estimate: dict | None, hr_max: float | None, trend=None) -> dict:
    return {"version": PHYSIO_VERSION, "vma": vma(efforts, day),
            "threshold_pace": threshold_pace(efforts, day, trend),
            "threshold_hr": threshold_hr(lthr_estimate, hr_max)}
