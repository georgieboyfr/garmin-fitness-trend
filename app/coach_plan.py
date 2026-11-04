"""
Coach (phase 4), étape 2 : plan périodisé vers la course A (fonctions pures, versionnées,
recalculées à chaque ouverture). Règles explicites, choisies par Greg ou tirées de repères
généraux (section 10 du brief) ; ce qui dépend du coureur est appris sur ses sorties.

- Affûtage selon la durée estimée de la course : une semaine sous 1 h 30, deux au-delà (Bosquet
  2007), charge réduite de 40 puis 60 % (une semaine : 50 %), intensité gardée, veille au repos.
- Avant, phases à rebours : spécifique, développement, foncier (environ 30 / 30 / 40 %) ; cycle 3
  semaines de charge et 1 allégée à −30 %, compté à rebours depuis l'affûtage.
- Charge pilotée par la fitness (modèle de Banister de la page Forme) : au plus +5 par semaine de
  charge, jamais plus de 10 % au-dessus du pic des 12 derniers mois, bornée par le temps
  disponible.
- Séances : jours « oui » puis optionnels, nombre maximal par semaine, un jour de repos au moins,
  sortie longue le jour le plus long, qualité jamais à côté d'une autre séance dure, habitude
  gardée à sa place avec un rôle selon la phase.
- Durées : charge convertie en minutes avec la charge par heure du coureur (médiane de ses
  sorties faciles et de ses séances sur 12 mois).
"""
import math
from datetime import date, timedelta
from statistics import median

from . import estimator, stats
from .metrics import ZONE_BOUNDS

PLAN_VERSION = 1
TAPER_SHORT_S = 5400            # course de moins de 1 h 30 : une semaine d'affûtage
TAPER_LOADS = {1: (0.5,), 2: (0.6, 0.4)}   # part de la dernière semaine de charge
RAMP_PER_WEEK = 5.0             # fitness gagnée au plus par semaine de charge (choix de Greg)
PEAK_MARGIN = 1.10              # jamais plus de 10 % au-dessus du pic des 12 derniers mois
RECOVERY_LOAD = 0.7             # semaine allégée : −30 % (choix de Greg)
CYCLE = 4                       # 3 semaines de charge, 1 allégée
PHASE_SHARES = (0.4, 0.3, 0.3)  # foncier, développement, spécifique
TAU = stats.TAU_FITNESS
WEEK_DECAY = math.exp(-7 / TAU)  # fitness gardée d'une semaine sur l'autre sans charge
EASY_MAX_HARD_SHARE = 0.10      # sortie facile : moins de 10 % du temps en zone 3 et plus
QUALITY_MIN_HARD_SHARE = 0.20   # séance : au moins 20 %
DEFAULT_RATES = (60.0, 85.0)    # HRSS par heure à défaut : endurance, séance (100 = 1 h au seuil)
RATE_DAYS = 365
DEFAULT_DAY_MIN = 60            # jour possible sans durée connue
MIN_SESSION_MIN = 20
QUALITY_MIN = {"foncier": 50, "développement": 55, "spécifique": 60, "affûtage": 45, "course": 40}
LONG_SHARE = 0.35               # sortie longue : environ un tiers du temps de la semaine
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ---------- état de départ ----------

def fitness_state(acts, today: date) -> dict:
    """Fitness à la veille de la semaine en cours (point de départ du plan) et pic des 12 mois."""
    daily = estimator._daily_load(acts)
    start_day = monday(today) - timedelta(days=1)
    if not daily:
        return {"fitness": 0.0, "peak_12m": 0.0}
    series = stats.banister(daily, min(daily), max(start_day, min(daily)))
    year_ago = start_day - timedelta(days=365)
    peak = max((p["fitness"] for p in series if p["date"] > year_ago), default=0.0)
    return {"fitness": round(series[-1]["fitness"], 1), "peak_12m": round(peak, 1)}


def load_rates(acts, today: date) -> dict:
    """Charge par heure (HRSS/h) des sorties faciles et des séances du coureur sur 12 mois."""
    since = today - timedelta(days=RATE_DAYS)
    easy, quality = [], []
    for a in acts:
        moving = a.get("moving_duration_s") or 0
        zones = [a.get(f"zone{i}_s") or 0 for i in range(1, 6)]
        if a["start"].date() < since or not a.get("hrss") or moving < 1200 or sum(zones) <= 0:
            continue
        hard = sum(zones[2:]) / sum(zones)
        rate = a["hrss"] / (moving / 3600)
        if hard < EASY_MAX_HARD_SHARE:
            easy.append(rate)
        elif hard >= QUALITY_MIN_HARD_SHARE:
            quality.append(rate)
    return {"easy": round(median(easy), 1) if len(easy) >= 3 else DEFAULT_RATES[0],
            "quality": round(median(quality), 1) if len(quality) >= 3 else DEFAULT_RATES[1],
            "personal": len(easy) >= 3, "easy_n": len(easy), "quality_n": len(quality)}


def weekly_load_for(fitness_now: float, fitness_next: float) -> float:
    """Charge hebdomadaire (répartie sur la semaine) qui fait passer la fitness de l'une à l'autre."""
    return max(0.0, 7 * (fitness_next - fitness_now * WEEK_DECAY) / (1 - WEEK_DECAY))


def fitness_after(fitness_now: float, load: float) -> float:
    return load / 7 + (fitness_now - load / 7) * WEEK_DECAY


# ---------- squelette : phases et types de semaines ----------

def skeleton(today: date, race_date: date, race_duration_s: float | None) -> list[dict]:
    """Semaines du plan, de la semaine en cours à celle de la course : phase et type."""
    first, last = monday(today), monday(race_date)
    n = (last - first).days // 7 + 1
    taper = 1 if (race_duration_s or 0) < TAPER_SHORT_S else 2
    taper = min(taper, n)
    m = n - taper
    if m < 3:
        phases = ["spécifique"] * m
    elif m < 6:
        dev = m // 2
        phases = ["développement"] * dev + ["spécifique"] * (m - dev)
    else:
        spec, dev = round(PHASE_SHARES[2] * m), round(PHASE_SHARES[1] * m)
        phases = ["foncier"] * (m - spec - dev) + ["développement"] * dev + ["spécifique"] * spec
    weeks = []
    for i, phase in enumerate(phases):
        from_taper = m - 1 - i            # 0 : la semaine juste avant l'affûtage
        weeks.append({"phase": phase, "kind": "allégée" if from_taper % CYCLE == CYCLE - 1 else "charge"})
    if taper == 2:
        weeks.append({"phase": "affûtage", "kind": "affûtage"})
    weeks.append({"phase": "course", "kind": "course"})
    for i, w in enumerate(weeks):
        w["monday"] = first + timedelta(weeks=i)
        w["index"] = i + 1
    return weeks


# ---------- jours retenus ----------

def chosen_days(availability: list[dict], max_sessions: int | None) -> list[dict]:
    """Jours de séance : « oui » d'abord, puis optionnels, au plus max_sessions et 6 (un jour de
    repos), chacun avec son temps maximal."""
    yes = [d for d in availability if d["status"] == "oui"]
    optional = [d for d in availability if d["status"] == "optionnel"]
    limit = min(max_sessions or 7, 6)
    picked = (yes + sorted(optional, key=lambda d: -(d.get("max_min") or 0)))[:limit]
    return sorted(({"weekday": d["weekday"], "status": d["status"],
                    "max_min": d.get("max_min") or d.get("usual_min") or DEFAULT_DAY_MIN} for d in picked),
                  key=lambda d: d["weekday"])


# ---------- séances ----------

def _pace(s_km: float | None) -> str:
    if not s_km:
        return ""
    s = round(s_km)
    return f"{s // 60}:{s % 60:02d} /km"


def _at(pace: str) -> str:
    return f" ({pace})" if pace else ""


def _quality(phase: str, kind: str, rank: int, trail: bool, week_in_phase: int, paces: dict,
             on_hills: bool) -> dict:
    """Séance de qualité selon la phase : type, libellé et description."""
    seuil, vma, race = _pace(paces.get("threshold")), _pace(paces.get("vma")), _pace(paces.get("race"))
    step = min(week_in_phase, 3)
    if kind in ("affûtage", "course"):
        return {"type": "rappel", "label": "Rappel d'allure",
                "description": f"20 min de footing puis 3 × 3 min à allure course{_at(race)}, "
                               "récupération 2 min : garder le rythme sans se fatiguer."}
    if phase == "foncier" or (kind == "allégée" and rank == 0):
        if on_hills:
            return {"type": "côtes", "label": "Côtes courtes",
                    "description": "Échauffement 15 min, puis 8 à 10 × 30 s de montée vive, retour en "
                                   "descendant au trot ; travail de force et de foulée."}
        return {"type": "lignes droites", "label": "Footing et lignes droites",
                "description": "Footing en endurance, puis 6 à 8 lignes droites de 20 s en accélération "
                               "progressive, récupération complète."}
    if phase == "développement":
        if rank == 0:
            reps = ("3 × 8 min", "3 × 10 min", "2 × 15 min", "3 × 12 min")[step]
            return {"type": "seuil", "label": "Seuil",
                    "description": f"Échauffement 15 min, {reps} à allure seuil{_at(seuil)}, zone 4, "
                                   "récupération 2 min au trot, retour au calme 10 min."}
        reps = ("10 × 30/30", "8 × 400 m", "6 × 600 m", "5 × 800 m")[step]
        return {"type": "fractionné", "label": "Fractionné",
                "description": f"Échauffement 20 min, {reps} à allure VMA{_at(vma)}, "
                               "récupération égale à l'effort, retour au calme 10 min."}
    # spécifique
    if rank == 0 and trail:
        return {"type": "côtes longues", "label": "Côtes longues",
                "description": "Échauffement 15 min, 4 à 6 × 4 min de montée à l'effort du seuil (zone 4), "
                               "retour en descente en soignant la technique."}
    if rank == 0:
        reps = ("3 × 10 min", "3 × 12 min", "2 × 20 min", "3 × 15 min")[step]
        return {"type": "allure course", "label": "Allure course",
                "description": f"Échauffement 15 min, {reps} à allure course{_at(race)}, "
                               "récupération 3 min, retour au calme 10 min."}
    return {"type": "seuil", "label": "Seuil",
            "description": f"Échauffement 15 min, 3 × 10 min à allure seuil{_at(seuil)}, "
                           "récupération 2 min, retour au calme 10 min."}


def _easy_text(lthr: float | None) -> str:
    cap = f", FC sous {round(ZONE_BOUNDS[1] * lthr)} bpm" if lthr else ""
    return f"Endurance fondamentale (zones 1 et 2{cap}), en aisance respiratoire."


def _adjacent(a: int, b: int) -> bool:
    return abs(a - b) == 1


def is_trail(race: dict) -> bool:
    """Trail : un GPX, ou plus de 15 m de D+ par km."""
    km = (race.get("distance_m") or 0) / 1000
    return bool(race.get("gpx_id")) or (km > 0 and (race.get("gain_m") or 0) / km > 15)


def _race_session(race: dict) -> dict:
    target = f" Objectif {race['target_text']}." if race.get("target_text") else ""
    return {"weekday": date.fromisoformat(race["race_date"]).weekday(), "type": "course",
            "label": f"Course : {race['name']}",
            "minutes": round(race["duration_s"] / 60) if race.get("duration_s") else None,
            "description": "L'objectif du plan." + target, "key": True, "hard": True}


def _quality_days(usable, long_day, n_quality, phase, kind, trail, race_wd, habit_by_day):
    """Jours des séances de qualité : jamais à côté de la sortie longue, d'une autre séance dure ou
    de la course ; côtes sur le jour d'une habitude vallonnée, les autres séances ailleurs."""
    hilly = {wd for wd, h in habit_by_day.items() if h.get("hilly")}
    others = [d for d in usable if not long_day or d["weekday"] != long_day["weekday"]]
    picked = []
    for rank in range(n_quality):
        candidates = [d for d in others if d not in picked
                      and not (long_day and _adjacent(d["weekday"], long_day["weekday"]))
                      and not any(_adjacent(d["weekday"], q["weekday"]) for q in picked)
                      and not (kind == "course" and _adjacent(d["weekday"], race_wd))]
        if not candidates:
            break
        hills = phase == "foncier" or (phase == "spécifique" and trail and rank == 0)
        def rank_key(d, hills=hills):
            avoid = (d["weekday"] not in hilly) if hills else (d["weekday"] in habit_by_day)
            return avoid, d["weekday"]
        candidates.sort(key=rank_key)
        picked.append(candidates[0])
    return picked, hilly


def build_week(week: dict, days: list[dict], load: float, rates: dict, race: dict, paces: dict,
               habits: list[dict], lthr: float | None, week_in_phase: int) -> dict:
    """Séances d'une semaine pour une charge visée : sortie longue, qualité, footings."""
    phase, kind = week["phase"], week["kind"]
    trail = is_trail(race)
    race_wd = date.fromisoformat(race["race_date"]).weekday()
    habit_by_day = {h["weekday"]: h for h in habits}
    sessions, usable = [], list(days)
    if kind == "course":
        sessions.append(_race_session(race))
        usable = [d for d in days if d["weekday"] < race_wd - 1]      # veille au repos
    if not usable:
        return _finish(week, sessions, load, rates)
    # sortie longue : le jour au temps maximal le plus long (à égalité, le plus tard dans la semaine)
    long_day = max(usable, key=lambda d: (d["max_min"], d["weekday"])) if kind != "course" else None
    if kind == "course":
        n_quality = 1
    elif len(usable) < 2:
        n_quality = 0
    else:
        n_quality = 2 if len(usable) >= 5 and kind == "charge" else 1
    quality_days, hilly = _quality_days(usable, long_day, n_quality, phase, kind, trail, race_wd,
                                        habit_by_day)
    q_min = QUALITY_MIN.get("course" if kind == "course" else phase, 50)
    total_min = load * 60 / rates["easy"]                                # en minutes d'endurance
    q_sessions = []
    for rank, d in enumerate(quality_days):
        q = _quality(phase, kind, rank, trail, week_in_phase, paces, d["weekday"] in hilly)
        minutes = min(d["max_min"], q_min)
        habit = habit_by_day.get(d["weekday"])
        if habit:
            q["label"] += f" ({habit['name']})"
        q_sessions.append({"weekday": d["weekday"], **q, "minutes": minutes, "key": rank == 0, "hard": True,
                           "habit": habit["name"] if habit else None})
        total_min -= minutes * rates["quality"] / rates["easy"]
    easy_days = [d for d in usable if d not in quality_days and d is not long_day]
    long_min = 0
    if long_day:
        wanted = max(MIN_SESSION_MIN, round(LONG_SHARE * load * 60 / rates["easy"]))
        room = max(MIN_SESSION_MIN, round(total_min - MIN_SESSION_MIN * len(easy_days)))
        long_min = min(long_day["max_min"], wanted, room)
        total_min -= long_min
    per_easy = total_min / len(easy_days) if easy_days else 0
    for d in easy_days:
        habit = habit_by_day.get(d["weekday"])
        minutes = round(min(d["max_min"], max(MIN_SESSION_MIN, per_easy)))
        keep = ""
        if habit:
            short = habit.get("moving_min") and minutes < habit["moving_min"] - 5
            keep = (" Ta sortie habituelle en version courte, à allure facile."
                    if short else " Garde ta sortie habituelle, à allure facile.")
        sessions.append({"weekday": d["weekday"], "type": "footing",
                         "label": "Footing" + (f" : {habit['name']}" if habit else ""),
                         "minutes": minutes,
                         "description": _easy_text(lthr) + keep, "key": False, "hard": False,
                         "habit": habit["name"] if habit else None})
    if long_day:
        gain = ""
        specific = phase in ("spécifique", "développement")
        if trail and race.get("duration_s") and race.get("gain_m") and specific:
            meters = round(race["gain_m"] * long_min * 60 / race["duration_s"], -1)
            gain = f", avec environ {meters:.0f} m de D+ (le dénivelé par heure de la course)"
        habit = habit_by_day.get(long_day["weekday"])
        sessions.append({"weekday": long_day["weekday"], "type": "sortie longue", "label": "Sortie longue",
                         "minutes": long_min, "description": _easy_text(lthr).rstrip(".") + gain + ".",
                         "key": not q_sessions, "hard": False, "habit": habit["name"] if habit else None})
    sessions.extend(q_sessions)
    return _finish(week, sessions, load, rates)


def _finish(week: dict, sessions: list[dict], load: float, rates: dict) -> dict:
    sessions.sort(key=lambda s: s["weekday"])
    for s in sessions:
        s["date"] = (week["monday"] + timedelta(days=s["weekday"])).isoformat()
        s["day"] = WEEKDAYS[s["weekday"]]
    minutes = sum(s["minutes"] or 0 for s in sessions if s["type"] != "course")
    planned = sum((s["minutes"] or 0) * (rates["quality"] if s["hard"] else rates["easy"]) / 60
                  for s in sessions if s["type"] != "course")
    return {**week, "monday": week["monday"].isoformat(), "target_load": round(load),
            "planned_load": round(planned), "minutes": minutes, "sessions": sessions}


# ---------- plan complet ----------

def build_plan(race: dict, today: date, acts, availability: list[dict], max_sessions: int | None,
               habits: list[dict], paces: dict, lthr: float | None) -> dict | None:
    """Plan de la semaine en cours à la course A. race : échéance du coach avec duration_s (temps
    estimé ou objectif) ; habits : habitudes gardées (weekday, name, hilly)."""
    race_date = date.fromisoformat(race["race_date"])
    if race_date < today:
        return None
    days = chosen_days(availability, max_sessions)
    rates = load_rates(acts, today)
    state = fitness_state(acts, today)
    weeks = skeleton(today, race_date, race.get("duration_s"))
    cap_fitness = state["peak_12m"] * PEAK_MARGIN if state["peak_12m"] else None
    capacity_min = sum(d["max_min"] for d in days)
    max_load = capacity_min / 60 * rates["easy"]
    fitness = state["fitness"]
    last_charge = None
    phase_counts = {}
    out = []
    taper_loads = TAPER_LOADS[sum(1 for w in weeks if w["kind"] in ("affûtage", "course"))]
    taper_i = 0
    for w in weeks:
        if w["kind"] == "charge":
            target = fitness + RAMP_PER_WEEK
            if cap_fitness:
                target = min(target, max(cap_fitness, fitness))
            load = min(weekly_load_for(fitness, target), max_load)
            last_charge = load
        elif w["kind"] == "allégée":
            load = RECOVERY_LOAD * (last_charge or weekly_load_for(fitness, fitness))
        else:
            base = last_charge or weekly_load_for(fitness, fitness)
            load = taper_loads[min(taper_i, len(taper_loads) - 1)] * base
            taper_i += 1
        week_in_phase = phase_counts.get(w["phase"], 0)
        phase_counts[w["phase"]] = week_in_phase + 1
        built = build_week(w, days, load, rates, race, paces, habits, lthr, week_in_phase)
        built["capped"] = w["kind"] == "charge" and load >= max_load - 0.5
        fitness = fitness_after(fitness, built["planned_load"])
        built["fitness_end"] = round(fitness, 1)
        out.append(built)
    capped = [w for w in out if w.get("capped")]
    return {"version": PLAN_VERSION, "start_fitness": state["fitness"], "peak_12m": state["peak_12m"],
            "capacity_limited": bool(capped), "capacity_fitness": round(max_load / 7, 1),
            "cap_fitness": round(cap_fitness, 1) if cap_fitness else None, "rates": rates,
            "days": days, "capacity_min": capacity_min, "weeks": out,
            "race_fitness": out[-1]["fitness_end"] if out else None}
