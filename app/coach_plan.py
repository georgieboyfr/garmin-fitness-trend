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

from . import coach_workouts as wk
from . import estimator, stats

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
MIN_EASY_MIN = 30               # un footing dure au moins 30 min
TRAIL_GAIN_PER_KM = 15.0        # sortie de trail : plus de 15 m de D+ par km
DEFAULT_EASY_VAM = 300          # m de D+ par heure en endurance, à défaut de sorties trail faciles
QUALITY_MAX_SHARE = 0.6         # deux séances de qualité seulement si elles laissent 40 % de la charge
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
        return {"fitness": 0.0, "fatigue": 0.0, "peak_12m": 0.0, "daily": {}}
    series = stats.banister(daily, min(daily), max(start_day, min(daily)))
    year_ago = start_day - timedelta(days=365)
    peak = max((p["fitness"] for p in series if p["date"] > year_ago), default=0.0)
    return {"fitness": round(series[-1]["fitness"], 1), "fatigue": series[-1]["fatigue"],
            "peak_12m": round(peak, 1), "daily": daily}


def simulate(state: dict, weeks: list[dict], rates: dict, today: date, race_date: date) -> dict:
    """Fitness et fatigue jour par jour (modèle de Banister) : charge réelle avant aujourd'hui,
    séances prévues ensuite. Fitness d'aujourd'hui, plus haute fitness du plan, fitness et
    fraîcheur (forme : fitness − fatigue de la veille) le matin de la course, fin de chaque semaine."""
    k_fit, k_fat = 1 - math.exp(-1 / stats.TAU_FITNESS), 1 - math.exp(-1 / stats.TAU_FATIGUE)
    planned = {}
    for w in weeks:
        for s in w["sessions"]:
            if s["type"] != "course" and s.get("minutes"):
                rate = rates["quality"] if s["hard"] else rates["easy"]
                planned[s["date"]] = planned.get(s["date"], 0.0) + s["minutes"] * rate / 60
    fit, fat = state["fitness"], state["fatigue"]
    d = date.fromisoformat(weeks[0]["monday"])
    out = {"today_fitness": None, "peak_fitness": fit, "week_end": {}}
    while d < race_date:
        if d == today:
            out["today_fitness"] = fit
        load = state["daily"].get(d, 0.0) if d < today else planned.get(d.isoformat(), 0.0)
        fit += (load - fit) * k_fit
        fat += (load - fat) * k_fat
        out["peak_fitness"] = max(out["peak_fitness"], fit)
        out["week_end"][monday(d).isoformat()] = fit
        d += timedelta(days=1)
    if out["today_fitness"] is None:
        out["today_fitness"] = fit
    out["race_fitness"], out["race_form"] = fit, fit - fat
    return out


def load_rates(acts, today: date) -> dict:
    """Charge par heure (HRSS/h) des sorties faciles et des séances du coureur sur 12 mois, et son
    allure habituelle en endurance (sorties faciles sur route plate), pour donner une distance."""
    since = today - timedelta(days=RATE_DAYS)
    easy, quality, paces, climbs = [], [], [], []
    for a in acts:
        moving = a.get("moving_duration_s") or 0
        zones = [a.get(f"zone{i}_s") or 0 for i in range(1, 6)]
        if a["start"].date() < since or not a.get("hrss") or moving < 1200 or sum(zones) <= 0:
            continue
        hard = sum(zones[2:]) / sum(zones)
        rate = a["hrss"] / (moving / 3600)
        if hard < EASY_MAX_HARD_SHARE:
            easy.append(rate)
            km = a.get("distance_km")
            if km and (a.get("gain_m") or 0) / km > TRAIL_GAIN_PER_KM:
                climbs.append(a["gain_m"] / (moving / 3600))
            if km and a.get("terrain") == "road" and (a.get("gain_m") or 0) / km < stats.FLAT_MAX_GAIN_PER_KM:
                paces.append(moving / a["distance_km"])
        elif hard >= QUALITY_MIN_HARD_SHARE:
            quality.append(rate)
    return {"easy": round(median(easy), 1) if len(easy) >= 3 else DEFAULT_RATES[0],
            "quality": round(median(quality), 1) if len(quality) >= 3 else DEFAULT_RATES[1],
            "personal": len(easy) >= 3, "easy_n": len(easy), "quality_n": len(quality),
            "easy_pace": round(median(paces), 1) if len(paces) >= 3 else None,
            "easy_vam": round(median(climbs)) if len(climbs) >= 3 else DEFAULT_EASY_VAM,
            "easy_vam_personal": len(climbs) >= 3}


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

HILL_TYPES = {"côtes", "côtes longues", "vma en côte", "montée au seuil", "marche en côte", "descente",
              "sprints en côte", "rappel"}


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
            "description": "L'objectif du plan." + target, "key": True, "hard": True, "steps": []}


def _pick_day(candidates, long_day, picked, kind, race_wd, habit_by_day, hills: bool):
    """Jour d'une séance de qualité : jamais à côté de la sortie longue, d'une autre séance dure ou
    de la course ; séance en côte sur le jour d'une habitude vallonnée, les autres ailleurs ; en
    semaine de course, le plus tard possible (2 à 4 jours avant)."""
    hilly = {wd for wd, h in habit_by_day.items() if h.get("hilly")}
    ok = [d for d in candidates if d not in picked
          and not (long_day and _adjacent(d["weekday"], long_day["weekday"]))
          and not any(_adjacent(d["weekday"], q["weekday"]) for q in picked)
          and not (kind == "course" and _adjacent(d["weekday"], race_wd))]
    if not ok:
        return None

    def key(d):
        if kind == "course":
            return (-d["weekday"],)
        avoid = (d["weekday"] not in hilly) if hills else (d["weekday"] in habit_by_day)
        return avoid, d["weekday"]
    return min(ok, key=key)


def build_week(week: dict, days: list[dict], load: float, rates: dict, race: dict, paces: dict,
               habits: list[dict], lthr: float | None, week_in_phase: int) -> dict:
    """Séances d'une semaine pour une charge visée : sortie longue, qualité, footings, prises dans
    le catalogue de coach_workouts et variées d'une semaine à l'autre. Durées rondes (5 min) ; un
    footing dure au moins MIN_EASY_MIN, sinon un jour de footing saute."""
    phase, kind = week["phase"], week["kind"]
    paces = {"lthr": lthr, "easy_vam": DEFAULT_EASY_VAM, **paces}
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
    others = [d for d in usable if d is not long_day]
    total_min = budget = load * 60 / rates["easy"]                       # en minutes d'endurance
    q_sessions, quality_days = [], []
    for rank in range(n_quality):
        proto = wk.quality(phase, kind, rank, trail, week_in_phase, paces, 999)
        hills = proto["type"] in HILL_TYPES
        d = _pick_day(others, long_day, quality_days, kind, race_wd, habit_by_day, hills)
        if d is None:
            break
        q = wk.quality(phase, kind, rank, trail, week_in_phase, paces, d["max_min"])
        cost = q["minutes"] * (rates["quality"] if q["hard"] else rates["easy"]) / rates["easy"]
        if rank > 0 and budget - total_min + cost > QUALITY_MAX_SHARE * budget:
            break                                       # une seule séance : la seconde mangerait la semaine
        habit = habit_by_day.get(d["weekday"])
        if habit:
            q["label"] += f" ({habit['name']})"
        q_sessions.append({"weekday": d["weekday"], **q, "key": rank == 0,
                           "habit": habit["name"] if habit else None})
        quality_days.append(d)
        total_min -= cost
    easy_days = [d for d in others if d not in quality_days]
    long_min = 0
    if long_day:
        # la sortie longue d'abord, la plus longue de la semaine ; ce sont les footings qui sautent
        wanted = LONG_SHARE * budget
        cap = min(long_day["max_min"], max(wanted, total_min / 2), total_min)
        long_min = max(MIN_EASY_MIN, wk.floor5(cap))
        total_min -= long_min
    if total_min < MIN_EASY_MIN:
        easy_days = []                                  # plus assez pour un footing : repos
    # pas de footing trop court : on retire un jour (le moins long, jamais celui d'une habitude)
    while len(easy_days) > 1 and total_min / len(easy_days) < MIN_EASY_MIN:
        easy_days.remove(min(easy_days, key=lambda d: (d["weekday"] in habit_by_day, d["max_min"])))
    per_easy = total_min / len(easy_days) if easy_days else 0
    for i, d in enumerate(easy_days):
        habit = habit_by_day.get(d["weekday"])
        minutes = max(MIN_EASY_MIN, wk.floor5(min(d["max_min"], per_easy + 2.5)))
        # variété : en trail, footings vallonnés et sur le plat en alternance ; en foncier et en
        # développement, un footing sur deux semaines finit par des lignes droites
        hilly = bool(habit and habit.get("hilly")) or (trail and (i + week["index"]) % 2 == 0)
        nxt = d["weekday"] + 1
        before_hard = (any(q["weekday"] == nxt for q in q_sessions)
                       or (long_day and long_day["weekday"] == nxt))
        if (not habit and kind == "charge" and phase in ("foncier", "développement")
                and i == len(easy_days) - 1 and week["index"] % 2 == 0 and not before_hard):
            s = wk.strides(max(MIN_EASY_MIN, minutes - 10), paces)
        else:
            s = wk.easy_run(minutes, paces, hilly, km=not hilly)
        if habit:
            short = habit.get("moving_min") and minutes < habit["moving_min"] - 5
            s["label"] = f"{s['label']} : {habit['name']}"
            s["description"] += (" Ta sortie habituelle en version courte." if short
                                 else " Garde ta sortie habituelle, à allure facile.")
        sessions.append({"weekday": d["weekday"], **s, "key": False,
                         "habit": habit["name"] if habit else None})
    if long_day:
        variant = wk.long_variant(phase, kind, trail, week_in_phase)
        s = wk.long_run(variant, long_min, paces, km=not trail)
        habit = habit_by_day.get(long_day["weekday"])
        sessions.append({"weekday": long_day["weekday"], **s, "key": not q_sessions,
                         "habit": habit["name"] if habit else None})
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
    paces = {**paces, "lthr": lthr, "easy": rates["easy_pace"], "easy_vam": rates["easy_vam"]}
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
        out.append(built)
    sim = simulate(state, out, rates, today, race_date)
    for w in out:
        w["fitness_end"] = round(sim["week_end"].get(w["monday"], fitness), 1)
    capped = [w for w in out if w.get("capped")]
    # fraîcheur relative (% de la fitness) : mêmes seuils que la page Forme, mais rapportés à la
    # fitness, pour valoir quel que soit le volume du coureur (convention d'intervals.icu)
    form_pct = sim["race_form"] / sim["race_fitness"] * 100 if sim["race_fitness"] > 0 else 0.0
    form_key, form_label = stats.form_zone(form_pct)
    if form_key == "transition":                   # le jour d'une course, être très frais n'est pas un défaut
        form_label = "Très frais, bien reposé"
    pre_taper = [w["fitness_end"] for w in out if w["kind"] in ("charge", "allégée")]
    return {"version": PLAN_VERSION, "start_fitness": round(sim["today_fitness"], 1),
            "peak_fitness": round(max(pre_taper) if pre_taper else sim["peak_fitness"], 1),
            "race_form": round(sim["race_form"], 1), "race_form_pct": round(form_pct),
            "race_form_zone": form_key,
            "race_form_label": form_label, "peak_12m": state["peak_12m"],
            "capacity_limited": bool(capped), "capacity_fitness": round(max_load / 7, 1),
            "cap_fitness": round(cap_fitness, 1) if cap_fitness else None, "rates": rates,
            "days": days, "capacity_min": capacity_min, "weeks": out,
            "race_fitness": round(sim["race_fitness"], 1)}
