"""
Modélisation Fitness / Fatigue / Form à partir des stress scores quotidiens,
selon les formules classiques de Banister (reprises par TrainingPeaks /
Elevate) :

    Fitness(day) = Fitness(day-1) + (Stress(day) - Fitness(day-1)) * (1 - e^(-1/42))
    Fatigue(day) = Fatigue(day-1) + (Stress(day) - Fatigue(day-1)) * (1 - e^(-1/7))
    Form(day)    = Fitness(day-1) - Fatigue(day-1)
"""

import math
from datetime import date, timedelta

TAU_FITNESS = 42.0
TAU_FATIGUE = 7.0


def compute_series(daily_stress: dict, start: date, end: date):
    """
    daily_stress : { "YYYY-MM-DD": total_hrss_du_jour }
    Retourne une liste ordonnée de dicts jour par jour entre start et end
    (bornes incluses), avec stress/fitness/fatigue/form.
    """
    k_fit = 1 - math.exp(-1 / TAU_FITNESS)
    k_fat = 1 - math.exp(-1 / TAU_FATIGUE)

    fitness = 0.0
    fatigue = 0.0
    out = []
    d = start
    while d <= end:
        stress = daily_stress.get(d.isoformat(), 0.0)
        form = fitness - fatigue  # forme du jour = état de la veille
        fitness = fitness + (stress - fitness) * k_fit
        fatigue = fatigue + (stress - fatigue) * k_fat
        out.append({
            "date": d.isoformat(),
            "stress": round(stress, 1),
            "fitness": round(fitness, 1),
            "fatigue": round(fatigue, 1),
            "form": round(form, 1),
            "zone": zone_for_form(form),
        })
        d += timedelta(days=1)
    return out


def zone_for_form(form: float) -> str:
    if form > 25:
        return "transition"
    if form > 5:
        return "freshness"
    if form > -10:
        return "neutral"
    if form > -30:
        return "optimal"
    return "overload"
