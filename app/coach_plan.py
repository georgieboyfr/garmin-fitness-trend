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
from statistics import median, quantiles

from . import coach_workouts as wk
from . import estimator, stats

PLAN_VERSION = 1
TAPER_SHORT_S = 7200            # course de moins de 2 h : une semaine d'affûtage (choix de Greg)
TAPER_LOADS = {1: (0.5,), 2: (0.6, 0.4)}   # part de la dernière semaine de charge
RAMP_PER_WEEK = 5.0             # fitness gagnée au plus par semaine de charge (choix de Greg)
PEAK_MARGIN = 1.10              # jamais plus de 10 % au-dessus du pic des 12 derniers mois
RECOVERY_LOAD = 0.7             # semaine allégée : −30 % (choix de Greg)
CYCLE = 4                       # 3 semaines de charge, 1 allégée
MIN_CHARGE_BEFORE_LIGHT = 2     # pas de semaine allégée avant 2 semaines de charge du plan
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
EASY_TIME_SHARE = 0.8           # 80/20 : 80 % du temps en endurance
CAPPED_MARGIN = 10              # charge prévue sous la visée de plus de 10 : les jours limitent
QUALITY_MAX_SHARE = 0.6         # deux séances de qualité seulement si elles laissent 40 % de la charge
LONG_SHARE = 0.35               # sortie longue : environ un tiers du temps de la semaine
# mélange appris sur les périodes où la fitness du coureur a monté (demande de Greg du 4 novembre 2026)
RISE_DAYS = 56                  # fenêtre de 8 semaines
RISE_MIN = 5.0                  # hausse de fitness d'au moins 5 points
RISE_MIN_PERIODS = 2            # au moins 2 périodes, sinon le 80/20 par défaut
EXCEPTIONAL_PCTL = 97           # sortie exceptionnelle : charge au-delà du 97e centile, ou plus de 3 h
EXCEPTIONAL_S = 3 * 3600
DEFAULT_RAMP_PCT = 10           # montée du volume, % par semaine (réglage posé au coureur : 10 ou 15)
LONG_RACE_SHARE = 0.9           # sortie longue allongée : jusqu'à 90 % de la durée de la course
LONG_MAX_MIN = 180              # jamais plus de 3 h
# plusieurs courses (étape 6) : repères généraux, à valider par Greg
RECOVERY_KM_PER_DAY = 3.0       # récupération : un jour sans séance dure par 3 km d'effort (Daniels)
RECOVERY_MIN_DAYS, RECOVERY_MAX_DAYS = 2, 21
C_RECOVERY_SHARE = 0.5          # course C courue comme une séance : moitié de la récupération
RECOVERY_LOAD_CUT = 0.5         # une semaine entière de récupération : charge −50 %
B_TAPER_DAYS = 3                # course B : mini-affûtage, 3 jours faciles avant, veille au repos
RACE_WEEK_LOAD = {"B": 0.5, "C": 0.7}     # semaine d'une course B ou C : entraînement autour, course en plus
MIN_LONG_MIN = 50               # sortie longue plus courte : un simple footing
RECOVERY_LOOKBACK_DAYS = RECOVERY_MAX_DAYS
A_MIN_GAP_DAYS = 56             # deux courses A à moins de 8 semaines : conflit
B_BEFORE_A_DAYS = 21            # course B moins de 3 semaines avant la A : conflit
C_BEFORE_A_DAYS = 7             # course C dans la semaine de la A : conflit
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


CONTINUE_WEEKS = 12             # « sans plan » : charge moyenne des semaines pleines passées, autant
CONTINUE_MAX_WEEKS = 52         # que le plan en compte, entre 12 et 52


def _run(state: dict, start: date, race_date: date, today: date, future) -> dict:
    """Fitness et fatigue jour par jour (modèle de Banister) de `start` à la veille de la course :
    charge réelle avant aujourd'hui, puis future(jour). Série quotidienne, fitness d'aujourd'hui,
    plus haute fitness, fitness et fraîcheur (forme : fitness − fatigue) le matin de la course."""
    k_fit, k_fat = 1 - math.exp(-1 / stats.TAU_FITNESS), 1 - math.exp(-1 / stats.TAU_FATIGUE)
    fit, fat = state["fitness"], state["fatigue"]
    out = {"today_fitness": None, "peak_fitness": fit, "week_end": {}, "series": []}
    d = start
    while d < race_date:
        if d == today:
            out["today_fitness"] = fit
        load = state["daily"].get(d, 0.0) if d < today else future(d)
        fit += (load - fit) * k_fit
        fat += (load - fat) * k_fat
        out["peak_fitness"] = max(out["peak_fitness"], fit)
        out["week_end"][monday(d).isoformat()] = fit
        out["series"].append({"date": d.isoformat(), "fitness": round(fit, 1), "form": round(fit - fat, 1)})
        d += timedelta(days=1)
    if out["today_fitness"] is None:
        out["today_fitness"] = fit
    out["race_fitness"], out["race_form"] = fit, fit - fat
    return out


def simulate(state: dict, weeks: list[dict], rates: dict, today: date, race_date: date,
             baseline: dict | None = None) -> dict:
    """Plan : séances prévues à partir d'aujourd'hui. Comparaison « sans plan » : la charge moyenne
    des 12 dernières semaines pleines, celle qui entretient la fitness actuelle, sans affûtage ;
    semaine médiane de ces semaines, pour la régularité."""
    planned = {}
    for w in weeks:
        for s in w["sessions"]:
            if not s.get("main") and not s.get("optional") and s.get("minutes"):
                planned[s["date"]] = planned.get(s["date"], 0.0) + session_load(s, rates)
    start = date.fromisoformat(weeks[0]["monday"])
    out = _run(state, start, race_date, today, lambda d: planned.get(d.isoformat(), 0.0))
    # « sans plan » : la charge moyenne d'une période aussi longue que le plan (12 semaines au moins,
    # 52 au plus), pour ne pas prolonger un été en montagne sur tout un hiver
    n = min(CONTINUE_MAX_WEEKS, max(CONTINUE_WEEKS, len(weeks)))
    base = state["daily"] if baseline is None else baseline       # charge par jour, sans l'exceptionnel
    weeks_load = [sum(base.get(start - timedelta(weeks=w, days=-i), 0.0) for i in range(7))
                  for w in range(1, n + 1)]
    mean = sum(weeks_load) / n
    out["continue"] = _run(state, start, race_date, today, lambda d: mean / 7)
    out["continue"]["weekly_load"] = round(mean)
    out["continue"]["median_week"] = round(median(weeks_load))
    out["continue"]["weeks"] = n
    return out


def load_rates(acts, today: date) -> dict:
    """Charge par heure (HRSS/h) des sorties faciles et des séances du coureur sur 12 mois, et son
    allure habituelle en endurance (sorties faciles sur route plate), pour donner une distance."""
    since = today - timedelta(days=RATE_DAYS)
    easy, quality, steady, paces, climbs = [], [], [], [], []
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
        else:
            steady.append(rate)
    e = round(median(easy), 1) if len(easy) >= 3 else DEFAULT_RATES[0]
    q = round(median(quality), 1) if len(quality) >= 3 else DEFAULT_RATES[1]
    return {"steady": round(median(steady), 1) if len(steady) >= 3 else round((e + q) / 2, 1),
            "easy": e, "quality": q, "personal": len(easy) >= 3, "easy_n": len(easy),
            "quality_n": len(quality),
            "easy_pace": round(median(paces), 1) if len(paces) >= 3 else None,
            "easy_vam": round(median(climbs)) if len(climbs) >= 3 else DEFAULT_EASY_VAM,
            "easy_vam_personal": len(climbs) >= 3}


def _run_kind(a: dict) -> str | None:
    zones = [a.get(f"zone{i}_s") or 0 for i in range(1, 6)]
    if sum(zones) <= 0:
        return None
    hard = sum(zones[2:]) / sum(zones)
    return "easy" if hard < EASY_MAX_HARD_SHARE else "hard" if hard >= QUALITY_MIN_HARD_SHARE else "steady"


def ordinary(acts, today: date, race_ids=(), keep_races: bool = False) -> list[dict]:
    """Sorties ordinaires d'avant aujourd'hui : sans les sorties exceptionnelles (plus de 3 h, ou
    charge au-delà du 97e centile, comme un séjour en montagne) ni, sauf keep_races, les courses
    confirmées (qui, elles, restent comptées même longues quand keep_races)."""
    past = [a for a in acts if a["start"].date() < today]
    loads = [a["hrss"] for a in past if a.get("hrss")]
    cut = quantiles(loads, n=100)[EXCEPTIONAL_PCTL - 1] if len(loads) >= 30 else math.inf
    out = []
    for a in past:
        race = a.get("id") in race_ids
        if race and not keep_races:
            continue
        if not race and ((a.get("hrss") or 0) > cut or (a.get("moving_duration_s") or 0) > EXCEPTIONAL_S):
            continue
        out.append(a)
    return out


def rising_periods(acts, today: date, race_ids=()) -> dict | None:
    """Ce qui a fait monter la fitness du coureur : périodes de 8 semaines où sa fitness, calculée
    sans les courses ni les sorties exceptionnelles (charge au-delà du 97e centile, plus de 3 h), a
    gagné au moins 5 points, sans chevauchement ; sorties, temps et charge par semaine, charge par
    heure et part du temps facile, soutenu et en séance. None sous 2 périodes."""
    if sum(1 for a in acts if a.get("hrss") and a["start"].date() < today) < 30:
        return None
    normal = [a for a in ordinary(acts, today, race_ids) if a.get("hrss")]
    daily = {}
    for a in normal:
        daily[a["start"].date()] = daily.get(a["start"].date(), 0.0) + a["hrss"]
    if not daily:
        return None
    fit = {p["date"]: p["fitness"] for p in stats.banister(daily, min(daily), today - timedelta(days=1))}
    days = sorted(fit)
    rises = sorted(((fit[days[i + RISE_DAYS]] - fit[days[i]], days[i]) for i in range(len(days) - RISE_DAYS)),
                   reverse=True)
    picked = []
    for rise, d0 in rises:
        if rise < RISE_MIN:
            break
        if all(abs((d0 - p).days) >= RISE_DAYS for _, p in picked):
            picked.append((rise, d0))
    if len(picked) < RISE_MIN_PERIODS:
        return None
    weeks = RISE_DAYS / 7
    per = []
    time = {"easy": 0.0, "steady": 0.0, "hard": 0.0}
    count = {"easy": 0, "steady": 0, "hard": 0}
    for _, d0 in picked:
        runs = [a for a in normal if d0 < a["start"].date() <= d0 + timedelta(days=RISE_DAYS)]
        per.append({"runs": len(runs) / weeks, "minutes": sum(a.get("moving_duration_s") or 0 for a in runs)
                    / 60 / weeks, "load": sum(a["hrss"] for a in runs) / weeks})
        for a in runs:
            k = _run_kind(a)
            if k:
                time[k] += a.get("moving_duration_s") or 0
                count[k] += 1
    total_t, total_n = sum(time.values()) or 1, sum(count.values()) or 1
    return {"periods": len(picked), "starts": sorted(d0.isoformat() for _, d0 in picked),
            "runs_per_week": round(median(p["runs"] for p in per), 1),
            "weekly_min": round(median(p["minutes"] for p in per)),
            "weekly_load": round(median(p["load"] for p in per)),
            "rate": round(sum(p["load"] for p in per) / (sum(p["minutes"] for p in per) / 60), 1),
            "time_share": {k: round(v / total_t, 3) for k, v in time.items()},
            "count_share": {k: round(v / total_n, 3) for k, v in count.items()}}


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
        # une semaine allégée récupère de semaines chargées : jamais avant 2 semaines de charge du plan
        light = from_taper % CYCLE == CYCLE - 1 and i >= MIN_CHARGE_BEFORE_LIGHT
        weeks.append({"phase": phase, "kind": "allégée" if light else "charge"})
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
                    "every": 1 if d["status"] == "oui" else d.get("every"),
                    "max_min": d.get("max_min") or d.get("usual_min") or DEFAULT_DAY_MIN} for d in picked),
                  key=lambda d: d["weekday"])


def week_days(days: list[dict], index: int) -> list[dict]:
    """Jours d'une semaine du plan : un jour optionnel avec une fréquence (une semaine sur n) entre
    dans le plan comme un jour « oui » une semaine sur n (les semaines n, 2n...) et disparaît les
    autres ; sans fréquence, il reste un bonus hors du plan."""
    out = []
    for d in days:
        every = d.get("every")
        if d["status"] != "optionnel" or not every:
            out.append(d)
        elif index % every == 0:
            out.append({**d, "status": "oui"})
    return out


# ---------- séances ----------

HILL_TYPES = {"côtes", "côtes longues", "vma en côte", "montée au seuil", "marche en côte", "descente",
              "sprints en côte", "rappel"}


def _adjacent(a: int, b: int) -> bool:
    return abs(a - b) == 1


def is_trail(race: dict) -> bool:
    """Trail : un GPX, ou plus de 15 m de D+ par km."""
    km = (race.get("distance_m") or 0) / 1000
    return bool(race.get("gpx_id")) or (km > 0 and (race.get("gain_m") or 0) / km > 15)


def _race_session(race: dict, main: bool = True) -> dict:
    target = f" Objectif {race['target_text']}." if race.get("target_text") else ""
    if main:
        label, text = f"Course : {race['name']}", "L'objectif du plan."
    elif race["priority"] == "B":
        label = f"Course B : {race['name']}"
        text = "Course importante : mini-affûtage avant, récupération après."
    else:
        label = f"Course C : {race['name']}"
        text = "Course de préparation, courue comme une grosse séance : elle remplace la séance clé."
    return {"weekday": date.fromisoformat(race["race_date"]).weekday(), "type": "course",
            "label": label, "main": main, "priority": race.get("priority"),
            "minutes": round(race["duration_s"] / 60) if race.get("duration_s") else None,
            "description": text + target, "key": True, "hard": True, "steps": [],
            "gain_m": race.get("gain_m") or 0}


# ---------- plusieurs courses ----------

def effort_km(race: dict) -> float:
    """Kilomètres-effort : distance plus 1 km par 100 m de D+ ; à défaut, la durée à 6 min/km."""
    km = (race.get("distance_m") or 0) / 1000 + (race.get("gain_m") or 0) / 100
    return km or (race.get("duration_s") or 0) / 360


def recovery_days(race: dict) -> int:
    """Jours sans séance dure ni sortie longue après une course : un par 3 km d'effort (repère de
    Daniels, un jour facile par 3 000 m de course), moitié pour une course C courue en séance."""
    days = effort_km(race) / RECOVERY_KM_PER_DAY
    if race.get("priority") == "C":
        days *= C_RECOVERY_SHARE
    return int(min(max(round(days), RECOVERY_MIN_DAYS), RECOVERY_MAX_DAYS))


def race_calendar(others: list[dict], start: date, race_date: date) -> dict:
    """Courses B et C (et passées récentes) autour du plan : course par date, jours au repos
    (veille d'une B), jours faciles (mini-affûtage d'une B, récupération de chaque course), avec la
    fin de récupération de chaque course."""
    out = {"races": {}, "rest": set(), "easy": set(), "recovery": set(), "recovery_end": {}}
    for r in others:
        d = date.fromisoformat(r["race_date"])
        if d >= race_date or d < start - timedelta(days=RECOVERY_LOOKBACK_DAYS):
            continue
        if d >= start:
            out["races"][d] = r
        if r.get("priority") == "B":
            out["rest"].add(d - timedelta(days=1))
            out["easy"].update(d - timedelta(days=k) for k in range(2, B_TAPER_DAYS + 1))
        n = recovery_days(r)
        # lendemain au repos complet (course B, ou C d'au moins une heure), puis récupération
        if r.get("priority") != "C" or (r.get("duration_s") or 0) >= 3600:
            out["rest"].add(d + timedelta(days=1))
        out["recovery"].update(d + timedelta(days=k) for k in range(1, n + 1))
        out["recovery_end"][r["race_date"]] = (d + timedelta(days=n)).isoformat()
    out["easy"] |= out["recovery"]
    out["easy"] -= set(out["races"])
    out["recovery"] -= set(out["races"])
    return out


def conflicts(upcoming: list[dict]) -> list[dict]:
    """Conflits du calendrier, avec des solutions au choix du coureur : deux courses A à moins de
    8 semaines, une course B moins de 3 semaines avant une A (sa récupération mange l'affûtage),
    une course C dans la semaine d'une A."""
    out = []
    a_races = [r for r in upcoming if r["priority"] == "A"]
    for a, b in zip(a_races, a_races[1:], strict=False):
        gap = (date.fromisoformat(b["race_date"]) - date.fromisoformat(a["race_date"])).days
        if gap < A_MIN_GAP_DAYS:
            out.append({"text": f"{a['name']} et {b['name']} : deux courses A à {gap // 7} semaines d'écart, "
                                "pas le temps de récupérer de l'une puis de s'affûter pour l'autre.",
                        "solutions": [{"label": f"Passer {x['name']} en B", "race_id": x["id"],
                                       "priority": "B"} for x in (b, a)]})
    for r in upcoming:
        if r["priority"] == "A":
            continue
        d = date.fromisoformat(r["race_date"])
        a = next((x for x in a_races if date.fromisoformat(x["race_date"]) > d), None)
        if not a:
            continue
        gap = (date.fromisoformat(a["race_date"]) - d).days
        if r["priority"] == "B" and gap < B_BEFORE_A_DAYS:
            out.append({"text": f"{r['name']} (B) à {gap} jours de {a['name']} (A) : sa récupération "
                                "empiète sur l'affûtage.",
                        "solutions": [{"label": f"Passer {r['name']} en C (courue en séance)",
                                       "race_id": r["id"], "priority": "C"}]})
        elif r["priority"] == "C" and gap < C_BEFORE_A_DAYS:
            out.append({"text": f"{r['name']} (C) à {gap} jours de {a['name']} (A) : en pleine semaine de "
                                "course, elle entame la fraîcheur.",
                        "solutions": [{"label": f"Retirer {r['name']} du calendrier", "race_id": r["id"],
                                       "delete": True}]})
    return out


def _pick_day(candidates, long_day, picked, kind, race_wd, habit_by_day, hills: bool):
    """Jour d'une séance de qualité : jamais à côté de la sortie longue, d'une autre séance dure ou
    de la course ; séance en côte sur le jour d'une habitude vallonnée, les autres ailleurs ; en
    semaine de course, le rappel 3 jours avant, sinon 4, et 2 en dernier recours : les deux
    derniers jours restent faciles, pour la fraîcheur (remarque de Greg du 4 novembre 2026)."""
    hilly = {wd for wd, h in habit_by_day.items() if h.get("hilly")}
    ok = [d for d in candidates if d not in picked
          and not (long_day and _adjacent(d["weekday"], long_day["weekday"]))
          and not any(_adjacent(d["weekday"], q["weekday"]) for q in picked)
          and not (kind == "course" and _adjacent(d["weekday"], race_wd))]
    if not ok:
        return None

    def key(d):
        if kind == "course":
            return ({3: 0, 4: 1, 2: 2}.get(race_wd - d["weekday"], 3), -d["weekday"])
        avoid = (d["weekday"] not in hilly) if hills else (d["weekday"] in habit_by_day)
        return avoid, d["weekday"]
    return min(ok, key=key)


def build_week(week: dict, days: list[dict], load: float, rates: dict, race: dict, paces: dict,
               habits: list[dict], lthr: float | None, week_in_phase: int,
               long_override: int | None = None, cal: dict | None = None, n_steady: int = 0,
               history_mix: bool = False) -> dict:
    """Séances d'une semaine pour une charge visée : sortie longue, qualité, footings, prises dans
    le catalogue de coach_workouts et variées d'une semaine à l'autre. Durées rondes (5 min) ; un
    footing dure au moins MIN_EASY_MIN, sinon un jour de footing saute. long_override : sortie
    longue allongée au-delà du temps du jour (exception à caler, réglage du coureur). cal : courses
    B et C (race_calendar) ; une course prend son jour, sa charge est comptée dans la semaine, ni
    séance dure ni sortie longue à côté ou pendant un mini-affûtage ou une récupération ; une
    course B limite la semaine à une séance de qualité, une course C remplace la séance clé."""
    phase, kind = week["phase"], week["kind"]
    paces = {"lthr": lthr, "easy_vam": DEFAULT_EASY_VAM, **paces}
    trail = is_trail(race)
    race_wd = date.fromisoformat(race["race_date"]).weekday()
    habit_by_day = {h["weekday"]: h for h in habits}
    sessions, usable = [], list(days)
    cal = cal or {"races": {}, "rest": set(), "easy": set()}
    monday_ = week["monday"]
    on = {wd: monday_ + timedelta(days=wd) for wd in range(7)}
    side = [(wd, cal["races"][on[wd]]) for wd in range(7) if on[wd] in cal["races"]]
    easy_wd = {wd for wd in range(7) if on[wd] in cal["easy"]}
    for _, r in side:
        sessions.append(_race_session(r, main=False))           # sa charge s'ajoute à la semaine
    side_wd = {wd for wd, _ in side}
    no_hard = easy_wd | {wd + k for wd in side_wd for k in (-1, 1)}
    usable = [d for d in usable if d["weekday"] not in side_wd
              and on[d["weekday"]] not in cal["rest"]]
    if kind == "course":
        sessions.append(_race_session(race))
        usable = [d for d in usable if d["weekday"] < race_wd - 1]      # veille au repos
    # jours optionnels : en bonus, hors du plan (choix de Greg du 4 novembre 2026) ; le plan tient sur
    # les jours « oui », sauf s'il n'y en a aucun
    optional = [d for d in usable if d.get("status") == "optionnel"]
    if len(optional) < len(usable):
        usable = [d for d in usable if d not in optional]
    else:
        optional = []
    if not usable:
        return _finish(week, sessions, load, rates)
    # sortie longue : le jour au temps maximal le plus long (à égalité, le plus tard dans la semaine),
    # hors récupération et mini-affûtage ; une course C d'au moins une heure en tient lieu
    long_pool = [d for d in usable if d["weekday"] not in no_hard]
    c_long = any(r["priority"] == "C" and (r.get("duration_s") or 0) >= 3600 for _, r in side)
    long_day = (max(long_pool, key=lambda d: (d["max_min"], d["weekday"]))
                if kind != "course" and long_pool and not c_long else None)
    if kind == "course":
        n_quality = 1
    elif len(usable) < 2:
        n_quality = 0
    else:
        n_quality = 2 if len(usable) >= 5 and kind == "charge" else 1
    if any(r["priority"] == "B" for _, r in side):
        n_quality = min(n_quality, 1)
    n_quality = max(0, n_quality - sum(1 for _, r in side if r["priority"] == "C"))
    others = [d for d in usable if d is not long_day]
    # bonus : le jour optionnel le plus long, ni en récupération ni à côté d'une course, hors course
    bonus_pool = [d for d in optional if d["weekday"] not in no_hard] if kind != "course" else []
    bonus_day = max(bonus_pool, key=lambda d: (d["max_min"], d["weekday"])) if bonus_pool else None
    total_min = budget = load * 60 / rates["easy"]                       # en minutes d'endurance
    q_sessions, quality_days = [], [{"weekday": wd} for wd in side_wd]
    q_pool = [d for d in others if d["weekday"] not in no_hard]
    for rank in range(n_quality):
        proto = wk.quality(phase, kind, rank, trail, week_in_phase, paces, 999)
        hills = proto["type"] in HILL_TYPES
        d = _pick_day(q_pool, long_day, quality_days, kind, race_wd, habit_by_day, hills)
        if d is None:
            break
        q = wk.quality(phase, kind, rank, trail, week_in_phase, paces, d["max_min"])
        if history_mix and kind == "charge" and q["hard"]:
            q = _fill(q, d["max_min"], paces)
        cost = q["minutes"] * (rates["quality"] if q["hard"] else rates["easy"]) / rates["easy"]
        if rank > 0 and budget - total_min + cost > QUALITY_MAX_SHARE * budget:
            break                                       # une seule séance : la seconde mangerait la semaine
        habit = habit_by_day.get(d["weekday"])
        if habit:
            q["label"] += f" ({habit['name']})"
        q_sessions.append({"weekday": d["weekday"], **q, "key": rank == 0 and not side,
                           "habit": habit["name"] if habit else None})
        quality_days.append(d)
        total_min -= cost
    easy_days = [d for d in others if d not in quality_days]
    room = min(long_day["max_min"], max(LONG_SHARE * budget, total_min / 2), total_min) if long_day else 0
    if long_day and room < MIN_LONG_MIN:
        easy_days.append(long_day)                      # trop peu de temps : un footing
        long_day = None
    long_min, variant, steady = 0, None, False
    if long_day:
        variant = wk.long_variant(phase, kind, trail, week_in_phase)
        # une semaine de charge sur deux, la sortie longue finit en allure soutenue (choix de Greg)
        steady = kind == "charge" and week["index"] % 2 == 0 and variant not in ("progressive", "spécifique")
        # la sortie longue d'abord, la plus longue de la semaine ; ce sont les footings qui sautent
        wanted = LONG_SHARE * budget
        cap = min(long_day["max_min"], max(wanted, total_min / 2), total_min)
        if long_override and long_override > long_day["max_min"] and not bonus_day:
            cap = min(long_override, total_min)          # allongée : prise sur les footings
        long_min = max(MIN_EASY_MIN, wk.floor5(cap))
        if steady:          # la fin soutenue charge plus : la sortie raccourcit d'autant, en endurance
            extra = wk.steady_finish_min(long_min) * (rates["quality"] / rates["easy"] - 1)
            long_min = max(MIN_EASY_MIN, wk.floor5(long_min - extra))
            total_min -= extra
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
        # en phase spécifique d'un trail, tous les footings sont vallonnés : le D+ de la course
        hilly = (bool(habit and habit.get("hilly"))
                 or (trail and (phase == "spécifique" or (i + week["index"]) % 2 == 0)))
        nxt = d["weekday"] + 1
        before_hard = (any(q["weekday"] == nxt for q in q_sessions)
                       or (long_day and long_day["weekday"] == nxt))
        if (n_steady and not habit and kind == "charge" and d["weekday"] not in easy_wd
                and not before_hard and minutes >= MIN_EASY_MIN + 10):
            # sortie soutenue, comme dans les hausses du coureur : même charge qu'un footing plus long
            ratio = rates["easy"] / (rates["easy"] + (rates["steady"] - rates["easy"]) * 0.6)
            s = wk.steady_run(max(MIN_EASY_MIN + 10, wk.floor5(minutes * ratio + 2.5)), paces, hilly)
            n_steady -= 1
        elif (not habit and kind == "charge" and phase in ("foncier", "développement")
                and d["weekday"] not in easy_wd
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
        s = wk.long_run(variant, long_min, paces, km=not trail, steady_finish=steady)
        if long_min > long_day["max_min"]:
            s["extended"] = True
            s["label"] += " allongée"
            s["description"] += (f" Plus long que ton temps du {WEEKDAYS[long_day['weekday']]} "
                                 f"({long_day['max_min']} min) : à caler, c'est la sortie qui prépare "
                                 "la durée de la course.")
        habit = habit_by_day.get(long_day["weekday"])
        sessions.append({"weekday": long_day["weekday"], **s, "key": not q_sessions and not side,
                         "habit": habit["name"] if habit else None})
    sessions.extend(q_sessions)
    if bonus_day:
        sessions.append(_bonus(bonus_day, long_min, long_override, variant, phase, kind, trail,
                               week_in_phase, paces, habit_by_day))
    return _finish(week, sessions, load, rates)


QUALITY_FILL_MAX = 20           # séance prolongée d'au plus 20 min de footing


def _fill(q: dict, day_max: float, paces: dict) -> dict:
    """Séance prolongée par un footing jusqu'au temps du jour (20 min au plus), comme les séances
    des hausses passées du coureur, comptées sortie entière."""
    add = wk.floor5(min(day_max - q["minutes"], QUALITY_FILL_MAX))
    if add < 10:
        return q
    steps = q["steps"] + [wk.step("cooldown", f"puis {add} min de footing", add,
                                  wk.target(wk.EASY, paces.get("lthr")))]
    return {**q, "steps": steps, "minutes": q["minutes"] + add}


def _bonus(day: dict, long_min: int, long_override: int | None, variant: str | None, phase: str, kind: str,
           trail: bool, week_in_phase: int, paces: dict, habit_by_day: dict) -> dict:
    """Sortie du jour optionnel, en bonus : une sortie longue en endurance (la sortie allongée de la
    semaine, s'il y en a une), hors de la charge prévue ; le plan ne compte pas dessus."""
    minutes = long_override or wk.floor5(min(day["max_min"], max(long_min, 60)))
    variant = variant or wk.long_variant(phase, kind, trail, week_in_phase)
    s = wk.long_run(variant, max(MIN_EASY_MIN, minutes), paces, km=not trail)
    s["label"] += " (optionnelle)"
    s["description"] = "En bonus, si tu es disponible : le plan ne compte pas dessus. " + s["description"]
    if long_override and minutes > day["max_min"]:
        s["extended"] = True
        s["description"] += (f" Plus long que ton temps du {WEEKDAYS[day['weekday']]} "
                             f"({day['max_min']} min) : à caler, c'est la sortie qui prépare la durée de "
                             "la course.")
    elif long_override:
        s["description"] += " C'est la sortie qui prépare la durée de la course : à privilégier."
    habit = habit_by_day.get(day["weekday"])
    return {"weekday": day["weekday"], **s, "key": False, "optional": True,
            "habit": habit["name"] if habit else None}


def session_load(s: dict, rates: dict) -> float:
    """Charge prévue d'une séance (HRSS) : séance dure à la charge par heure des séances ; sinon en
    endurance, sauf ses étapes d'effort (fin soutenue d'une sortie longue, lignes droites)."""
    minutes = s.get("minutes") or 0
    if s["hard"]:
        return minutes * rates["quality"] / 60
    work = sum(x["minutes"] for x in s.get("steps", []) if x["kind"] == "work")
    work_rate = rates.get("steady", rates["quality"]) if s["type"] == "footing soutenu" else rates["quality"]
    return ((minutes - work) * rates["easy"] + work * work_rate) / 60


def _finish(week: dict, sessions: list[dict], load: float, rates: dict) -> dict:
    sessions.sort(key=lambda s: s["weekday"])
    for s in sessions:
        s["date"] = (week["monday"] + timedelta(days=s["weekday"])).isoformat()
        s["day"] = WEEKDAYS[s["weekday"]]
    counted = [s for s in sessions if not s.get("main") and not s.get("optional")]
    minutes = sum(s["minutes"] or 0 for s in counted)
    planned = sum(session_load(s, rates) for s in counted)
    gain = sum(s.get("gain_m") or 0 for s in counted)
    return {**week, "monday": week["monday"].isoformat(), "target_load": round(load),
            "planned_load": round(planned), "minutes": minutes, "gain_m": round(gain, -1),
            "sessions": sessions}


# ---------- plan complet ----------

def _race_form(pct: float) -> tuple[str, str]:
    """Zone de fraîcheur relative (% de la fitness) le jour d'une course : mêmes seuils que la page
    Forme, rapportés à la fitness ; être très frais un jour de course n'est pas un défaut."""
    key, label = stats.form_zone(pct)
    return key, "Très frais, bien reposé" if key == "transition" else label


PERIOD_LABELS = {"vacances": "Vacances", "maladie": "Maladie", "blessure": "Blessure",
                 "deplacement": "Déplacement", "chargee": "Semaine chargée"}
PERIOD_REST = ("maladie", "blessure")   # sans séance par défaut, reprise progressive ensuite
REPRISE_DAYS = 7                        # semaine de reprise après une maladie ou une blessure


def period_days(days: list[dict], monday_: date, periods: list[dict], availability: list[dict]) -> list[dict]:
    """Jours d'une semaine avec les périodes particulières du coureur (vacances, maladie...) : les
    jours d'une période remplacent les disponibilités, avec le nombre de séances prévu par semaine
    (au prorata des jours de la période dans la semaine ; aucune pour une maladie ou une blessure
    sans nombre), placées d'abord sur les jours habituels, jamais deux jours de suite si possible,
    chacune avec la durée maximale saisie (sinon celle du jour, sinon la plus longue des jours)."""
    if not periods:
        return days
    by_wd = {d["weekday"]: d for d in availability}
    longest = max((d.get("max_min") or 0 for d in availability), default=0) or DEFAULT_DAY_MIN
    out = list(days)
    for p in periods:
        start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        inside = [wd for wd in range(7) if start <= monday_ + timedelta(days=wd) <= end]
        if not inside:
            continue
        out = [d for d in out if d["weekday"] not in inside]
        n = p.get("sessions")
        if n is None:
            n = 0 if p["kind"] in PERIOD_REST else len([d for d in days if d["weekday"] in inside])
            share = 1.0
        else:
            share = len(inside) / 7
        n = min(len(inside), int(n * share + 0.5))
        order = sorted(inside, key=lambda wd: (by_wd.get(wd, {}).get("status", "non") == "non",
                                               -(by_wd.get(wd, {}).get("max_min") or 0), wd))
        picked = []
        for wd in order:                             # d'abord sans jours de suite, puis comme on peut
            if len(picked) < n and all(abs(wd - x) > 1 for x in picked):
                picked.append(wd)
        for wd in order:
            if len(picked) < n and wd not in picked:
                picked.append(wd)
        for wd in picked:
            minutes = p.get("max_min") or by_wd.get(wd, {}).get("max_min") or longest
            out.append({"weekday": wd, "status": "oui", "every": 1, "max_min": minutes, "period": p["kind"]})
    return sorted(out, key=lambda d: d["weekday"])


def _period_events(monday_: date, periods: list[dict]) -> list[dict]:
    end_week = monday_ + timedelta(days=6)
    out = []
    for p in periods or []:
        start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if start <= end_week and end >= monday_:
            out.append({"kind": p["kind"], "label": PERIOD_LABELS.get(p["kind"], p["kind"]),
                        "start": p["start"], "end": p["end"], "sessions": p.get("sessions")})
        elif p["kind"] in PERIOD_REST and end < monday_ <= end + timedelta(days=REPRISE_DAYS):
            out.append({"kind": "reprise", "label": f"Reprise après {PERIOD_LABELS[p['kind']].lower()}",
                        "start": p["start"], "end": p["end"], "sessions": None})
    return out


def _core_max(days: list[dict]) -> float:
    core = [d for d in days if d.get("status") != "optionnel"] or days
    return max(d["max_min"] for d in core)


def long_extensions(weeks: list[dict], days: list[dict], race: dict, enabled: bool) -> dict:
    """Sorties longues allongées (réglage du coureur) : une semaine de charge spécifique sur deux,
    la dernière juste avant l'affûtage, au-delà du jour le plus long, en progression régulière
    jusqu'à 90 % de la durée de la course (3 h au plus) ; avec un jour optionnel plus long retenu
    une semaine sur n, les semaines où il l'est. {index de semaine : minutes}."""
    if not enabled or not days or not race.get("duration_s"):
        return {}
    day_max = _core_max(days)
    goal = min(LONG_RACE_SHARE * race["duration_s"] / 60, LONG_MAX_MIN)
    if goal <= day_max:
        return {}
    spec = [w["index"] for w in weeks if w["phase"] == "spécifique" and w["kind"] == "charge"]
    roomy = [i for i in spec if _core_max(week_days(days, i)) > day_max]
    picked = roomy or sorted(spec[::-1][::2])
    out = {}
    for j, i in enumerate(picked, 1):
        minutes = wk.floor5(day_max + (goal - day_max) * j / len(picked))
        if minutes > day_max:
            out[i] = minutes
    return out


READY_WEEKS = 8                 # « aujourd'hui » : les 8 dernières semaines pleines


def readiness(acts, today: date, weeks: list[dict], race: dict, n_days: int) -> list[dict]:
    """Ce que la course demande, ce que le coureur fait aujourd'hui (8 dernières semaines pleines,
    courses comprises) et ce que le plan lui fait faire : sortie la plus longue, sorties longues,
    D+ par semaine (trail), séances par mois, semaines régulières, fraîcheur du jour J. Chaque
    repère : now, plan, need (None si sans objet), et ok quand le plan atteint le besoin."""
    start = monday(today) - timedelta(weeks=READY_WEEKS)
    recent = [a for a in acts if start <= a["start"].date() < monday(today)]
    race_min = (race.get("duration_s") or 0) / 60
    long_need = min(LONG_RACE_SHARE * race_min, LONG_MAX_MIN) if race_min else None
    long_min = max(60.0, 0.5 * race_min) if race_min else 90.0
    pre = [w for w in weeks if w["kind"] in ("charge", "allégée")]
    last8 = pre[-READY_WEEKS:]
    sess = [x for w in weeks for x in w["sessions"] if x["type"] != "course"]
    by_week = {}
    for a in recent:
        k = (a["start"].date() - start).days // 7
        by_week.setdefault(k, []).append(a)
    weekly_gain = sorted(sum(a.get("gain_m") or 0 for a in by_week.get(k, [])) for k in range(READY_WEEKS))
    spec = [w["gain_m"] for w in weeks if w["phase"] == "spécifique" and w["kind"] == "charge"]
    hard_recent = sum(1 for a in recent if _run_kind(a) == "hard")
    hard_plan = sum(1 for w in pre for x in w["sessions"] if x["hard"] and x["type"] != "course")
    regular = max(1, n_days)
    out = [
        {"key": "long", "label": "Sortie la plus longue", "unit": "min",
         "now": round(max(((a.get("moving_duration_s") or 0) / 60 for a in recent), default=0)),
         "plan": max((x["minutes"] or 0 for x in sess if x["type"] == "sortie longue"), default=0),
         "need": round(long_need) if long_need else None,
         "why": "La durée de la course s'apprend en sortie longue : jusqu'à 90 % de son temps, 3 h au plus."},
        {"key": "longs", "label": f"Sorties de {round(long_min)} min et plus", "unit": "en 8 sem.",
         "now": sum(1 for a in recent if (a.get("moving_duration_s") or 0) / 60 >= long_min),
         "plan": sum(1 for w in last8 for x in w["sessions"]
                     if x["type"] == "sortie longue" and (x["minutes"] or 0) >= long_min),
         "need": None, "why": "Sur les 8 semaines avant l'affûtage : la moitié de la durée de la course."},
        {"key": "hard", "label": "Séances par mois", "unit": "",
         "now": round(hard_recent / READY_WEEKS * 4, 1),
         "plan": round(hard_plan / max(1, len(pre)) * 4, 1), "need": None,
         "why": "Séances de qualité (au moins 20 % du temps en zone 3 et plus), courses comprises."},
        {"key": "regular", "label": f"Semaines d'au moins {regular} sorties", "unit": "sur 8",
         "now": sum(1 for k in range(READY_WEEKS) if len(by_week.get(k, [])) >= regular),
         "plan": sum(1 for w in last8 if len([x for x in w["sessions"] if not x.get("optional")]) >= regular),
         "need": None, "why": "La régularité fait progresser plus que les grosses semaines isolées."},
    ]
    if is_trail(race) and race.get("gain_m"):
        out.insert(1, {"key": "gain", "label": "D+ par semaine", "unit": "m",
                       "now": round(weekly_gain[len(weekly_gain) // 2], -1),
                       "plan": round(sorted(spec)[len(spec) // 2], -1) if spec else 0,
                       "need": round(race["gain_m"], -1),
                       "why": "Semaine médiane ; en phase spécifique, le plan vise le D+ de la course."})
    for r in out:
        r["ok"] = r["need"] is not None and r["plan"] >= 0.95 * r["need"]
        r["better"] = r["plan"] > r["now"]
    return out


def _spread(index: int, per_week: float) -> int:
    """Nombre d'occurrences en semaine `index` d'une chose prévue `per_week` fois par semaine en
    moyenne, réparties régulièrement (0,5 : une semaine sur deux)."""
    return math.floor(index * per_week) - math.floor((index - 1) * per_week)


def build_plan(race: dict, today: date, acts, availability: list[dict], max_sessions: int | None,
               habits: list[dict], paces: dict, lthr: float | None,
               options: dict | None = None, others: list[dict] | None = None,
               race_ids=()) -> dict | None:
    """Plan de la semaine en cours à la course A. race : échéance du coach avec duration_s (temps
    estimé ou objectif) ; habits : habitudes gardées (weekday, name, hilly) ; options : réglages
    posés au coureur (ramp_pct : montée du volume en % par semaine ; long_extension : sorties
    longues allongées une semaine de charge spécifique sur deux) ; others : les autres courses du
    calendrier (B, C, passées récentes), avec duration_s, distance_m et gain_m."""
    options = options or {}
    ramp_pct = options.get("ramp_pct") or DEFAULT_RAMP_PCT
    extend = options.get("long_extension", True)
    race_date = date.fromisoformat(race["race_date"])
    if race_date < today:
        return None
    days = chosen_days(availability, max_sessions)
    rates = load_rates(acts, today)
    paces = {**paces, "lthr": lthr, "easy": rates["easy_pace"], "easy_vam": rates["easy_vam"]}
    state = fitness_state(acts, today)
    weeks = skeleton(today, race_date, race.get("duration_s"))
    cap_fitness = state["peak_12m"] * PEAK_MARGIN if state["peak_12m"] else None
    # capacité : les jours « oui », et les jours optionnels au prorata de leur fréquence ; ceux sans
    # fréquence sont des bonus hors du plan
    core_days = [d for d in days if d.get("status") != "optionnel"] or days
    capacity_min = round(sum(d["max_min"] for d in core_days)
                         + sum(d["max_min"] / d["every"] for d in days
                               if d.get("status") == "optionnel" and d.get("every") and d not in core_days))
    # plafond : tout le temps disponible, réparti comme dans les hausses passées du coureur (temps
    # facile, soutenu, en séance), sinon en 80/20 (endurance, effort)
    history = rising_periods(acts, today, race_ids)
    if history:
        sh = history["time_share"]
        blended = sh["easy"] * rates["easy"] + sh["steady"] * rates["steady"] + sh["hard"] * rates["quality"]
    else:
        blended = EASY_TIME_SHARE * rates["easy"] + (1 - EASY_TIME_SHARE) * rates["quality"]
    # sorties soutenues : la part de ses hausses, en nombre de sorties, répartie au fil des semaines
    n_core = len([d for d in days if d.get("status") != "optionnel"])
    steady_per_week = history["count_share"]["steady"] * n_core if history else 0.0
    max_load = capacity_min / 60 * blended

    periods = options.get("periods") or []

    def days_of(w: dict) -> list[dict]:
        return period_days(week_days(days, w["index"]), w["monday"], periods, availability)

    def week_cap(w: dict) -> float:
        wd = days_of(w)
        core = [d for d in wd if d.get("status") != "optionnel"] or wd
        return sum(d["max_min"] for d in core) / 60 * blended
    fitness = state["fitness"]
    last_charge = None
    phase_counts = {}
    out = []
    taper_loads = TAPER_LOADS[sum(1 for w in weeks if w["kind"] in ("affûtage", "course"))]
    taper_i = 0
    extended = long_extensions(weeks, days, race, extend)
    cal = race_calendar(others or [], weeks[0]["monday"], race_date)
    for w in weeks:
        if w["kind"] == "charge":
            target = fitness + RAMP_PER_WEEK
            if cap_fitness:
                target = min(target, max(cap_fitness, fitness))
            # volume : au plus +ramp_pct % sur la dernière semaine de charge (au départ, la charge
            # qui entretient la fitness actuelle) ; après une allégée, retour au niveau d'avant
            # la montée suit la charge visée, pas le temps de la semaine (un weekend libre de temps
            # en temps ne la fait pas redescendre)
            ref = last_charge or weekly_load_for(state["fitness"], state["fitness"])
            last_charge = min(weekly_load_for(fitness, target), (1 + ramp_pct / 100) * max(ref, 1.0),
                              max(max_load, week_cap(w)))
            load = min(last_charge, week_cap(w))
        elif w["kind"] == "allégée":
            load = RECOVERY_LOAD * (last_charge or weekly_load_for(fitness, fitness))
        else:
            base = last_charge or weekly_load_for(fitness, fitness)
            load = taper_loads[min(taper_i, len(taper_loads) - 1)] * base
            taper_i += 1
        # courses B et C : semaine allégée autour de la course, récupération au prorata des jours
        dates_ = [w["monday"] + timedelta(days=k) for k in range(7)]
        for d in dates_:
            if d in cal["races"]:
                load *= RACE_WEEK_LOAD.get(cal["races"][d]["priority"], RACE_WEEK_LOAD["B"])
        recovering = [d for d in dates_ if d in cal["recovery"]]
        load *= 1 - RECOVERY_LOAD_CUT * len(recovering) / 7
        # périodes particulières : la charge tient dans les séances prévues ; reprise progressive
        # la semaine après une maladie ou une blessure
        events = _period_events(w["monday"], periods)
        if events:
            load = min(load, week_cap(w))
            if any(e["kind"] == "reprise" for e in events):
                load *= RECOVERY_LOAD
        week_in_phase = phase_counts.get(w["phase"], 0)
        phase_counts[w["phase"]] = week_in_phase + 1
        built = build_week(w, days_of(w), load, rates, race, paces, habits, lthr,
                           week_in_phase,
                           extended.get(w["index"]), cal,
                           _spread(w["index"], steady_per_week), bool(history))
        built["periods"] = events
        built["events"] = [{"name": r["name"], "until": cal["recovery_end"][r["race_date"]]}
                           for r in others or [] if r["race_date"] in cal["recovery_end"]
                           and r["race_date"] < (w["monday"] + timedelta(days=6)).isoformat()
                           and cal["recovery_end"][r["race_date"]] >= w["monday"].isoformat()]
        if w["phase"] == "spécifique" and is_trail(race) and race.get("gain_m"):
            built["gain_target"] = round(race["gain_m"], -1)        # D+ de la course, visé chaque semaine
        built["capped"] = w["kind"] == "charge" and not events and (load >= week_cap(w) - 0.5
                                                      or built["planned_load"] < load - CAPPED_MARGIN)
        fitness = fitness_after(fitness, built["planned_load"])
        out.append(built)
    baseline = {}
    for a in ordinary(acts, today, race_ids, keep_races=True):
        if a.get("hrss"):
            baseline[a["start"].date()] = baseline.get(a["start"].date(), 0.0) + a["hrss"]
    sim = simulate(state, out, rates, today, race_date, baseline)
    for w in out:
        w["fitness_end"] = round(sim["week_end"].get(w["monday"], fitness), 1)
    capped = [w for w in out if w.get("capped")]
    # fraîcheur relative (% de la fitness) : mêmes seuils que la page Forme, mais rapportés à la
    # fitness, pour valoir quel que soit le volume du coureur (convention d'intervals.icu)
    form_pct = sim["race_form"] / sim["race_fitness"] * 100 if sim["race_fitness"] > 0 else 0.0
    form_key, form_label = _race_form(form_pct)
    cont = sim["continue"]
    cont_pct = cont["race_form"] / cont["race_fitness"] * 100 if cont["race_fitness"] > 0 else 0.0
    cont_key, cont_label = _race_form(cont_pct)
    hills = sum(1 for w in out for x in w["sessions"] if x["type"] in HILL_TYPES and x["type"] != "rappel")
    longs = sum(1 for w in out for x in w["sessions"] if x["type"] == "sortie longue")
    longest = max((x["minutes"] for w in out for x in w["sessions"] if x["type"] == "sortie longue"),
                  default=0)
    pre_taper = [w["fitness_end"] for w in out if w["kind"] in ("charge", "allégée")]
    return {"version": PLAN_VERSION, "start_fitness": round(sim["today_fitness"], 1),
            "peak_fitness": round(max(pre_taper) if pre_taper else sim["peak_fitness"], 1),
            "race_form": round(sim["race_form"], 1), "race_form_pct": round(form_pct),
            "race_form_zone": form_key,
            "continue": {"peak_fitness": round(max((p["fitness"] for p in cont["series"]),
                                                   default=cont["race_fitness"]), 1),
                         "race_fitness": round(cont["race_fitness"], 1),
                         "race_form": round(cont["race_form"], 1),
                         "race_form_pct": round(cont_pct), "race_form_zone": cont_key,
                         "race_form_label": cont_label, "weekly_load": cont["weekly_load"],
                         "median_week": cont["median_week"], "weeks": cont["weeks"]},
            "series": [{**p, "continue_fitness": c["fitness"], "continue_form": c["form"]}
                       for p, c in zip(sim["series"], cont["series"], strict=True)],
            "hill_sessions": hills, "long_runs": longs, "longest_run": longest, "history": history,
            "readiness": readiness(ordinary(acts, today, race_ids, keep_races=True), today, out, race,
                                   len([d for d in days if d.get("status") != "optionnel"])),
            "steady_runs": sum(1 for w in out for x in w["sessions"] if x["type"] == "footing soutenu"),
            "options": {"ramp_pct": ramp_pct, "long_extension": extend},
            "race_form_label": form_label, "peak_12m": state["peak_12m"],
            "capacity_limited": bool(capped), "capacity_fitness": round(max_load / 7, 1),
            "cap_fitness": round(cap_fitness, 1) if cap_fitness else None, "rates": rates,
            "days": days, "capacity_min": capacity_min, "weeks": out,
            "race_fitness": round(sim["race_fitness"], 1)}
