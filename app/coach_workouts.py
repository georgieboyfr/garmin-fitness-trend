"""
Bibliothèque de séances du coach : séances structurées en étapes (échauffement, effort répété,
récupération, retour au calme), chacune avec sa cible, décrite de façon structurée (FC en plage,
allure en plage, % de la VMA, effort perçu sur 10 et sensation) pour pouvoir l'afficher dans
l'unité de son choix ; le texte d'une cible suit toujours le même ordre : allure, FC, effort.

- Endurance : plage de FC tirée de la FC de réserve (Karvonen, 60 à 70 %) ou de la FC max (65 à
  75 %), au choix dans l'admin ; les intensités au-dessus suivent les zones de Friel (% de la LTHR).
- Fractionné VMA : l'allure dépend de la longueur de la fraction (30/30 et 200 m à 105 % de la
  VMA, 400 m à 102 %, 600 m à 100 %, 800 m à 98 %, 1 000 m à 95 %), repères courants des plans
  français ; VMA testée saisie dans l'admin, sinon estimée sur les sorties.
- Toute séance finit par au moins 10 min de retour au calme ; le complément d'une séance allongée
  au temps habituel du coureur est réparti entre l'échauffement et le retour au calme.
- Allure spécifique en blocs qui s'allongent au fil de la phase spécifique, selon la course (5 km,
  10 km, semi, marathon) : l'entonnoir du général au spécifique (Canova), blocs de 3 × 2 000 à
  3 × 5 000 m pour un semi, par exemple.
- Sorties longues : fin soutenue sur route ; en terrain vallonné, le bloc soutenu au milieu, pour
  redescendre ensuite en endurance. Variante sur le plat avec variations d'allure, et alternative
  sur le plat à la même charge estimée pour une sortie vallonnée (neige, boue).

Inspirations : présentation des séances de time-to-run (MIT), étapes typées avec répétitions et
cibles en plage d'OpenAthlete (idée seulement, aucun code repris). Séances de trail d'après les
repères courants (World Athletics, TrainingPeaks, vert.run, campus.coach, u-run) : sprints en côte
de moins de 10 s, côtes courtes de 30 s à 1 min, longues de 3 min et plus, montée continue au
seuil, marche rapide en forte pente, descente travaillée à introduire progressivement ;
récupération en redescendant au trot, de l'ordre de 1 à 3 fois l'effort. Variété : chaque créneau
a plusieurs variantes, qui tournent d'une semaine à l'autre ; le palier monte à chaque tour.
"""
import math

ROUND_MIN = 5
WARMUP_MIN = 15
COOLDOWN_MIN = 10                  # retour au calme : jamais moins de 10 min (demande de Greg)
DEFAULT_VMA_PACE = 270.0           # s/km, à défaut d'estimation (4:30 /km)
PACE_BAND = 0.02                   # plage d'allure : ±2 %
# endurance : % de la FC de réserve (Karvonen) ou de la FC max, au choix dans l'admin
EASY_HRR = (0.60, 0.70)
EASY_HRMAX = (0.65, 0.75)
EASY_LTHR = (0.75, 0.85)           # à défaut de FC max : zone 1 de Friel
# allure des fractions selon leur longueur, en part de la VMA
VMA_SHARE = {"30/30": 1.05, 200: 1.05, 300: 1.03, 400: 1.02, 500: 1.01, 600: 1.00, 800: 0.98, 1000: 0.95}

# intensités : FC (« easy » pour la plage d'endurance, sinon en % de la LTHR, zones de Friel),
# effort perçu (1 à 10) et sensation (facile, moyen, dur, très dur)
EASY = {"key": "endurance", "hr": "easy", "rpe": "3 à 4", "feel": "facile"}
STEADY = {"key": "soutenu", "hr": (0.85, 0.92), "rpe": "5 à 6", "feel": "moyen"}
TEMPO = {"key": "tempo", "hr": (0.90, 0.95), "rpe": "6 à 7", "feel": "moyen"}
THRESHOLD = {"key": "seuil", "hr": (0.95, 1.00), "rpe": "7", "feel": "dur"}
VO2 = {"key": "vma", "hr": (1.00, None), "rpe": "9", "feel": "très dur"}
HILL_SHORT = {"key": "côte", "hr": None, "rpe": "8 à 9", "feel": "très dur"}
RACE_TRAIL = {"key": "course trail", "hr": (0.88, 0.95), "rpe": "6 à 7", "feel": "moyen"}
RACE_ROAD = {"key": "allure course", "hr": None, "rpe": "6 à 8", "feel": "dur"}
RECOVERY = {"key": "récupération", "hr": None, "rpe": "2", "feel": "très facile"}
FAST = {"key": "vif", "hr": None, "rpe": "7 à 8", "feel": "dur"}
DOWN = {"key": "descente", "hr": None, "rpe": "5 à 6", "feel": "moyen"}
HIKE = {"key": "marche", "hr": (0.85, 0.95), "rpe": "6", "feel": "moyen"}
SPRINT = {"key": "sprint", "hr": None, "rpe": "9", "feel": "très dur"}
STRIDE = {"key": "accélération", "hr": None, "rpe": "7 à 8", "feel": "dur"}


def easy_hr(method: str | None, hr_max: float | None, hr_rest: float | None,
            lthr: float | None = None) -> tuple[int, int] | None:
    """Plage de FC de l'endurance fondamentale : 60 à 70 % de la FC de réserve (Karvonen), ou 65 à
    75 % de la FC max ; à défaut de FC max, la zone 1 de Friel (75 à 85 % de la LTHR)."""
    if hr_max and method == "fcmax":
        return round(EASY_HRMAX[0] * hr_max), round(EASY_HRMAX[1] * hr_max)
    if hr_max and hr_rest and hr_rest < hr_max:
        return tuple(round(hr_rest + k * (hr_max - hr_rest)) for k in EASY_HRR)
    if lthr:
        return round(EASY_LTHR[0] * lthr), round(EASY_LTHR[1] * lthr)
    return None


def warm(compact: bool, normal: float = WARMUP_MIN) -> float:
    return 10 if compact else normal


def cool(compact: bool = False) -> float:
    return COOLDOWN_MIN


def round5(minutes: float) -> int:
    return int(ROUND_MIN * round(minutes / ROUND_MIN))


def floor5(minutes: float) -> int:
    return int(ROUND_MIN * math.floor(minutes / ROUND_MIN))


def pace_text(s_km: float | None) -> str:
    if not s_km:
        return ""
    s = round(s_km)
    return f"{s // 60}:{s % 60:02d}"


def pace_band(s_km: float | None, band: float = PACE_BAND) -> str:
    if not s_km:
        return ""
    return f"{pace_text(s_km * (1 - band))} à {pace_text(s_km * (1 + band))} /km"


def _minutes(m: float) -> str:
    if m < 1:
        return f"{round(m * 60)} s"
    whole = int(m)
    sec = round((m - whole) * 60)
    return f"{whole} min" + (f" {sec:02d}" if sec else "")


def hr_range(intensity: dict, p: dict) -> tuple[int | None, int | None] | None:
    """FC de l'intensité en battements : plage d'endurance du coureur, sinon % de la LTHR ; la
    borne basse d'une allure soutenue ne descend pas dans l'endurance."""
    hr = intensity.get("hr")
    if hr == "easy":
        return p.get("easy_hr") or easy_hr(None, None, None, p.get("lthr"))
    lthr = p.get("lthr")
    if not hr or not lthr:
        return None
    low, high = (round(k * lthr) if k else None for k in hr)
    easy = p.get("easy_hr")
    if low and easy and intensity["key"] == "soutenu":
        low = max(low, easy[1] + 1)
    return low, high


def target(intensity: dict, p: dict | float | None, pace: str = "", pace_s: float | None = None,
           band: float = PACE_BAND) -> str:
    """Cible lisible, toujours dans le même ordre : allure, FC en plage, effort perçu et sensation.
    p : les repères du coureur (ou, pour les anciens appels, sa LTHR)."""
    return target_info(intensity, p, pace, pace_s, band)["text"]


def target_info(intensity: dict, p: dict | float | None, pace: str = "", pace_s: float | None = None,
                band: float = PACE_BAND) -> dict:
    """Cible structurée (FC, allure, % de la VMA, % de la FC max, effort, sensation) et son texte."""
    if not isinstance(p, dict):
        p = {"lthr": p}
    if pace_s and not pace:
        pace = pace_band(pace_s, band)
    parts = [pace] if pace else []
    hr = hr_range(intensity, p)
    info = {"key": intensity["key"], "rpe": intensity["rpe"], "feel": intensity["feel"]}
    if hr:
        low, high = hr
        info["hr"] = [low, high]
        if low and high:
            parts.append(f"FC {low} à {high}")
        elif high:
            parts.append(f"FC sous {high}")
        else:
            parts.append(f"FC au-dessus de {low}")
        if p.get("hr_max"):
            info["hr_max_pct"] = [round(x / p["hr_max"] * 100) if x else None for x in hr]
    if pace_s:
        info["pace"] = [round(pace_s * (1 - band)), round(pace_s * (1 + band))]
        if p.get("vma"):
            info["vma_pct"] = round(p["vma"] / pace_s * 100)
    parts.append(f"effort {intensity['rpe']}/10, {intensity['feel']}")
    info["text"] = " · ".join(parts)
    return info


def step(kind: str, text: str, minutes: float, cible: str | dict = "") -> dict:
    """Étape : warmup, work (effort, répété ou non), recovery, cooldown, steady. cible : texte, ou
    cible structurée (target_info)."""
    if isinstance(cible, dict):
        return {"kind": kind, "text": text, "minutes": minutes, "target": cible["text"], "intensity": cible}
    return {"kind": kind, "text": text, "minutes": minutes, "target": cible}


def _session(type_: str, label: str, steps: list[dict], note: str = "") -> dict:
    total = sum(s["minutes"] for s in steps)
    return {"type": type_, "label": label, "minutes": round5(total), "steps": steps, "description": note,
            "hard": True}


def _warmup(minutes: float, p: dict) -> dict:
    return step("warmup", f"Échauffement {_minutes(minutes)} en endurance", minutes, target_info(EASY, p))


def _cooldown(minutes: float, p: dict) -> dict:
    return step("cooldown", f"Retour au calme {_minutes(minutes)} en endurance, en ralentissant", minutes,
                target_info(EASY, p))


def _easy_pace(p: dict, km: bool = True) -> str:
    return f"≈ {pace_text(p.get('easy'))} /km" if p.get("easy") and km else ""


def resize(s: dict, extra: float, p: dict) -> dict:
    """Séance allongée de `extra` minutes en endurance : un tiers à l'échauffement, le reste au
    retour au calme (la séance garde sa fin au calme, l'échauffement reste raisonnable)."""
    steps = [dict(x) for x in s["steps"]]
    first = next((x for x in steps if x["kind"] in ("warmup", "steady")), None)
    last = next((x for x in reversed(steps) if x["kind"] == "cooldown"), None)
    to_first = floor5(extra / 3) if first else 0
    for x, add in ((first, to_first), (last, extra - to_first)):
        if x is None or not add:
            continue
        old = x["minutes"]
        x["text"] = x["text"].replace(_minutes(old), _minutes(old + add), 1)
        x["minutes"] = old + add
    return {**s, "steps": steps, "minutes": round5(sum(x["minutes"] for x in steps))}


# paliers : (répétitions, durée en min, récupération en min)
SEUIL = [(3, 8, 2), (3, 10, 2), (2, 15, 3), (4, 10, 2), (3, 12, 3), (2, 20, 4)]
VMA = [("30/30", 10), ("30/30", 12), ("m", 8, 400), ("m", 6, 600), ("m", 5, 800), ("m", 4, 1000)]
COTES_COURTES = [8, 10, 12]                        # × 30 s
COTES_LONGUES = [(4, 4), (5, 4), (4, 5), (3, 8)]   # × min de montée
ALLURE = [(3, 10, 3), (3, 12, 3), (2, 20, 4), (3, 15, 3)]
VMA_REST = {400: 1.5, 600: 2.0, 800: 2.5, 1000: 3.0}   # récupération au trot, min
# allure spécifique en blocs (répétitions, mètres, récupération en min), du plus court au plus long :
# le volume à allure course s'allonge au fil de la phase spécifique
SPECIFIC = {
    "5k": [(8, 600, 1.5), (6, 800, 2), (5, 1000, 2), (4, 1200, 2.5), (3, 1600, 3)],
    "10k": [(5, 1000, 1.5), (6, 1000, 1.5), (4, 1500, 2), (3, 2000, 2.5), (3, 3000, 3)],
    "semi": [(3, 2000, 2), (4, 2000, 2), (3, 3000, 2.5), (2, 5000, 3), (3, 5000, 3)],
    "marathon": [(3, 3000, 2), (2, 5000, 3), (3, 5000, 3), (2, 8000, 4), (3, 6000, 3)],
}
RACE_NAMES = {"5k": "5 km", "10k": "10 km", "semi": "semi", "marathon": "marathon"}


def seuil(level: int, p: dict, compact: bool = False) -> dict:
    reps, work, rest = SEUIL[min(level, len(SEUIL) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × {work} min au seuil", reps * work,
                  target_info(THRESHOLD, p, pace_s=p.get("threshold"))),
             step("recovery", f"récupération {rest} min au trot entre les blocs", (reps - 1) * rest,
                  target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("seuil", "Seuil", steps, "Allure « confortablement difficile » : on pourrait la tenir "
                                             "une heure. Les blocs doivent rester réguliers.")


def vma_pace(p: dict, length) -> float:
    """Allure d'une fraction de VMA selon sa longueur (30/30, mètres)."""
    base = p.get("vma") or DEFAULT_VMA_PACE
    share = VMA_SHARE.get(length) or (VMA_SHARE[1000] if isinstance(length, int) and length > 1000 else 1.0)
    return base / share


def vma(level: int, p: dict, compact: bool = False) -> dict:
    entry = VMA[min(level, len(VMA) - 1)]
    if entry[0] == "30/30":
        reps = entry[1]
        pace = vma_pace(p, "30/30")
        work = step("work", f"{reps} × 30 s vite / 30 s au trot, sans arrêt", reps * 1.0,
                    target_info(VO2, p, pace_s=pace))
        steps = [_warmup(warm(compact, 20), p), work]
    else:
        _, reps, meters = entry
        rest = VMA_REST[meters]
        pace = vma_pace(p, meters)
        share = round(VMA_SHARE[meters] * 100)
        steps = [_warmup(warm(compact, 20), p),
                 step("work", f"{reps} × {meters} m à {share} % de la VMA", reps * meters / 1000 * pace / 60,
                      target_info(VO2, p, pace_s=pace)),
                 step("recovery", f"récupération {_minutes(rest)} au trot", (reps - 1) * rest,
                      target_info(RECOVERY, p))]
    steps.append(_cooldown(cool(), p))
    return _session("vma", "VMA", steps, "Vite mais en contrôle : la dernière répétition aussi rapide que "
                                         "la première. Plus la fraction est courte, plus l'allure est vive. "
                                         "Arrêter si l'allure s'effondre.")


PYRAMIDE = [(1, 2, 3, 2, 1), (1, 2, 3, 4, 3, 2, 1), (2, 3, 4, 4, 3, 2)]   # min d'effort


def pyramid(level: int, p: dict, compact: bool = False) -> dict:
    """Pyramide : efforts de 1 à 4 min qui montent puis redescendent, entre l'allure 5 km et le
    seuil, récupération au trot de la moitié de l'effort précédent."""
    blocks = PYRAMIDE[min(level, len(PYRAMIDE) - 1)]
    pace = p["threshold"] * 0.96 if p.get("threshold") else None
    work = sum(blocks)
    rest = sum(b / 2 for b in blocks[:-1])
    steps = [_warmup(warm(compact, 20), p),
             step("work", "pyramide " + "-".join(str(b) for b in blocks) + " min, vite mais régulier", work,
                  target_info({"key": "pyramide", "hr": (0.97, 1.03), "rpe": "7 à 8", "feel": "dur"}, p,
                              pace_s=pace)),
             step("recovery", "récupération au trot : la moitié de l'effort qui précède (30 s après 1 min, "
                              "1 min après 2 min...)", rest, target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("pyramide", "Pyramide", steps, "Partir prudemment : les efforts longs du milieu se "
                                                   "courent à la même allure que les courts.")


def strides(total_min: float, p: dict) -> dict:
    """Footing et lignes droites d'environ total_min : le footing, 8 accélérations, le retour au calme."""
    base_min = max(15, round5(total_min - 20))
    steps = [step("steady", f"{_minutes(base_min)} en endurance", base_min,
                  target_info(EASY, p, _easy_pace(p))),
             step("work", "8 × 20 s en accélération progressive, jamais à fond", 8 * 20 / 60,
                  target_info(STRIDE, p)),
             step("recovery", "récupération 1 min au trot ou en marchant entre les accélérations", 7,
                  target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    s = _session("lignes droites", "Footing et lignes droites", steps,
                 "Les accélérations restent fluides : travail de foulée, pas de fatigue.")
    s["hard"] = False
    return s


def hills_short(level: int, p: dict, compact: bool = False) -> dict:
    reps = COTES_COURTES[min(level, len(COTES_COURTES) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × 30 s de montée vive, pente moyenne", reps * 0.5,
                  target_info(HILL_SHORT, p)),
             step("recovery", "récupération : redescente au trot, 1 min 30 (3 fois l'effort)", reps * 1.5,
                  target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("côtes", "Côtes courtes", steps, "Travail de force : genoux hauts, appuis dynamiques, "
                                                     "buste droit.")


def hills_long(level: int, p: dict, compact: bool = False) -> dict:
    reps, work = COTES_LONGUES[min(level, len(COTES_LONGUES) - 1)]
    rest = round(work * 0.75, 1)
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × {work} min de montée", reps * work, target_info(THRESHOLD, p)),
             step("recovery", f"récupération : redescente au trot, environ {_minutes(rest)}, repartir dès "
                              "que le souffle est revenu", reps * rest, target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("côtes longues", "Côtes longues", steps,
                    "À l'effort du seuil, pas à l'allure : en côte, la FC et la sensation guident. En "
                    "descente, relâché et pieds légers, c'est aussi un entraînement.")


def race_pace(level: int, p: dict, compact: bool = False) -> dict:
    """Allure course en blocs : en mètres selon la course (SPECIFIC) quand l'allure visée est
    connue, sinon en minutes."""
    kind = p.get("race_kind")
    if kind in SPECIFIC and p.get("race"):
        reps, meters, rest = SPECIFIC[kind][min(level, len(SPECIFIC[kind]) - 1)]
        work_min = reps * meters / 1000 * p["race"] / 60
        what = (f"{reps} × {meters / 1000:g} km".replace(".", ",") if meters >= 1000
                else f"{reps} × {meters} m")
        steps = [_warmup(warm(compact, 20), p),
                 step("work", f"{what} à allure {RACE_NAMES[kind]}", work_min,
                      target_info(RACE_ROAD, p, pace_s=p["race"], band=0.01)),
                 step("recovery", f"récupération {_minutes(rest)} au trot", (reps - 1) * rest,
                      target_info(RECOVERY, p)),
                 _cooldown(cool(), p)]
        return _session("allure course", f"Allure {RACE_NAMES[kind]}", steps,
                        "L'allure du jour J, en blocs qui s'allongent au fil de la préparation : la tenir "
                        "régulière, sans aller plus vite.")
    reps, work, rest = ALLURE[min(level, len(ALLURE) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × {work} min à allure course", reps * work,
                  target_info(RACE_ROAD, p, pace_s=p.get("race"), band=0.01)),
             step("recovery", f"récupération {rest} min au trot", (reps - 1) * rest,
                  target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("allure course", "Allure course", steps,
                    "Mémoriser les sensations de l'allure du jour J.")


def reminder(trail: bool, p: dict, compact: bool = False) -> dict:
    if trail:
        steps = [_warmup(warm(compact, 20), p),
                 step("work", "3 × 3 min de montée à l'effort de course", 9, target_info(RACE_TRAIL, p)),
                 step("recovery", "récupération : redescente souple au trot, environ 2 min 30 après "
                      "chaque montée", 7.5, target_info(RECOVERY, p)),
                 _cooldown(cool(), p)]
        return _session("rappel", "Rappel en côte", steps, "Retrouver les sensations du terrain sans se "
                                                           "fatiguer.")
    steps = [_warmup(warm(compact, 20), p),
             step("work", "3 × 3 min à allure course", 9,
                  target_info(RACE_ROAD, p, pace_s=p.get("race"), band=0.01)),
             step("recovery", "récupération 2 min au trot", 4, target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("rappel", "Rappel d'allure", steps, "Garder le rythme sans se fatiguer.")


def easy_steps(minutes: float, p: dict, km: bool = True) -> list[dict]:
    """Footing ou sortie longue : une seule étape, en endurance."""
    pace = p.get("easy")
    dist = f", environ {round(minutes * 60 / pace)} km sur le plat" if km and pace else ""
    return [step("steady", f"{_minutes(minutes)} en endurance fondamentale{dist}", minutes,
                 target_info(EASY, p, _easy_pace(p, km)))]


def fit(make, level: int, day_max: float) -> dict:
    """Palier le plus haut, jusqu'à `level`, dont la durée tient dans le temps du jour ; à défaut,
    le premier palier avec un échauffement raccourci."""
    for lv in range(level, -1, -1):
        s = make(lv)
        if s["minutes"] <= day_max:
            return s
    return make(0, compact=True)


# ---------- séances supplémentaires (variété) ----------

TEMPO_MIN = [20, 25, 30, 35]                      # min en continu
FARTLEK = [8, 10, 12]                             # × 1 min vif / 1 min footing
HILL_SPRINTS = [6, 8, 10]                         # × 10 s
HILLS_MEDIUM = [6, 8, 10]                         # × 1 min
UPHILL_TEMPO = [15, 20, 25, 30]                   # min de montée continue
POWER_HIKE = [(4, 4), (5, 4), (4, 6), (5, 6)]     # × min de marche rapide
DOWNHILL = [4, 6, 8]                              # × 1 min 30 de descente
WALK = "marcher dans les montées raides pour rester sous la FC visée"


def steady_finish_min(minutes: float) -> int:
    """Durée du bloc soutenu d'une sortie longue."""
    return 15 if minutes < 90 else 20


def tempo(level: int, p: dict, compact: bool = False) -> dict:
    minutes = TEMPO_MIN[min(level, len(TEMPO_MIN) - 1)]
    pace = p["threshold"] * 1.04 if p.get("threshold") else None
    steps = [_warmup(warm(compact), p),
             step("work", f"{minutes} min en continu, allure soutenue", minutes,
                  target_info(TEMPO, p, pace_s=pace)),
             _cooldown(cool(), p)]
    return _session("tempo", "Tempo", steps, "Un cran sous le seuil : soutenu mais régulier, la respiration "
                                             "rythmée sans être haletante.")


def fartlek(level: int, p: dict, compact: bool = False) -> dict:
    reps = FARTLEK[min(level, len(FARTLEK) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × 1 min vif", reps, target_info(FAST, p)),
             step("recovery", "récupération 1 min en footing, sans s'arrêter", reps - 1,
                  target_info(EASY, p)),
             _cooldown(cool(), p)]
    return _session("fartlek", "Fartlek", steps, "Au gré du terrain : les accélérations à la sensation, "
                                                 "plus vite que le seuil, moins vite qu'un sprint.")


def hill_sprints(level: int, p: dict, compact: bool = False) -> dict:
    reps = HILL_SPRINTS[min(level, len(HILL_SPRINTS) - 1)]
    base = 10 if compact else 25
    steps = [step("steady", f"{base} min de footing", base, target_info(EASY, p)),
             step("work", f"{reps} × 10 s de sprint en côte raide", reps * 10 / 60, target_info(SPRINT, p)),
             step("recovery", "récupération complète : redescente en marchant, 1 min 30", (reps - 1) * 1.5,
                  target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    s = _session("sprints en côte", "Footing et sprints en côte", steps,
                 "Puissance et foulée sans fatigue : l'effort est trop court pour faire monter la FC.")
    s["hard"] = False
    return s


def hills_medium(level: int, p: dict, compact: bool = False) -> dict:
    reps = HILLS_MEDIUM[min(level, len(HILLS_MEDIUM) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × 1 min de montée vive", reps, target_info(HILL_SHORT, p)),
             step("recovery", "récupération : redescente au trot, 2 min", reps * 2, target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("vma en côte", "VMA en côte", steps, "Pente moyenne (5 à 8 %) : monter vite en restant "
                                                         "relâché, la même vitesse à chaque répétition.")


def uphill_tempo(level: int, p: dict, compact: bool = False) -> dict:
    minutes = UPHILL_TEMPO[min(level, len(UPHILL_TEMPO) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{minutes} min de montée continue", minutes, target_info(THRESHOLD, p)),
             step("recovery", f"redescente souple au trot, sans forcer, environ {_minutes(minutes * 0.6)}",
                  minutes * 0.6, target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("montée au seuil", "Montée continue au seuil", steps,
                    "Une longue montée à l'effort du seuil, en courant ou en marchant vite selon la pente. "
                    "Sans montée assez longue, enchaîner les côtes du coin sans pause, au même effort.")


def power_hike(level: int, p: dict, compact: bool = False) -> dict:
    reps, work = POWER_HIKE[min(level, len(POWER_HIKE) - 1)]
    steps = [_warmup(warm(compact), p),
             step("work", f"{reps} × {work} min de marche rapide en forte pente (plus de 15 %)", reps * work,
                  target_info(HIKE, p)),
             step("recovery", f"récupération : redescente au trot, environ {_minutes(work * 0.6)}",
                  reps * work * 0.6, target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("marche en côte", "Marche rapide en côte", steps,
                    "Mains sur les cuisses ou bâtons, buste penché, pas courts et rapides : la marche "
                    "efficace des fortes pentes de course.")


def downhill(level: int, p: dict, compact: bool = False) -> dict:
    reps = DOWNHILL[min(level, len(DOWNHILL) - 1)]
    steps = [_warmup(warm(compact, 20), p),
             step("work", f"{reps} × 1 min 30 de descente rapide sur sentier", reps * 1.5,
                  target_info(DOWN, p)),
             step("recovery", "récupération : remontée en marchant, environ 3 min", reps * 3,
                  target_info(RECOVERY, p)),
             _cooldown(cool(), p)]
    return _session("descente", "Descente travaillée", steps,
                    "Foulée courte et rapide, regard loin devant, relâché. Les cuisses travaillent beaucoup "
                    "en descente (fatigue musculaire jusqu'à 48 h et plus) : commencer avec peu de "
                    "répétitions, jamais dans les 3 semaines avant la course.")


# ---------- footings et sorties longues ----------

def _easy_session(type_: str, label: str, steps: list[dict], note: str) -> dict:
    s = _session(type_, label, steps, note)
    s["hard"] = False
    return s


def _gain_text(gain: float) -> str:
    return f", environ {gain:.0f} m de D+" if gain else ""


def easy_run(minutes: float, p: dict, hilly: bool, km: bool = True) -> dict:
    """Footing, sur le plat ou vallonné (moitié de la vitesse de montée en endurance)."""
    if hilly:
        gain = round(p.get("easy_vam", 0) * minutes / 60 * 0.5, -1)
        text = f"{_minutes(minutes)} en endurance sur un parcours vallonné{_gain_text(gain)}"
        s = _easy_session("footing vallonné", "Footing vallonné",
                          [step("steady", text, minutes, target_info(EASY, p))],
                          f"Il faut {WALK} : c'est voulu.")
        s["gain_m"] = gain
        return s
    return _easy_session("footing", "Footing", easy_steps(minutes, p, km),
                         "En aisance respiratoire : tu peux parler.")


def steady_run(minutes: float, p: dict, hilly: bool = False) -> dict:
    """Sortie soutenue (endurance active) : 15 min faciles, un bloc soutenu, 10 min de retour au
    calme ; plus chargée qu'un footing, moins qu'une séance (ni récupération ni répétitions)."""
    block = max(15, round5(minutes - 25))
    where = "sur un parcours vallonné, l'effort plutôt que l'allure" if hilly else "sur le plat"
    steps = [step("warmup", "15 min en endurance", 15, target_info(EASY, p)),
             step("work", f"{block} min en allure soutenue, {where}", block, target_info(STEADY, p)),
             _cooldown(cool(), p)]
    s = _easy_session("footing soutenu", "Sortie soutenue", steps,
                      "Plus vite qu'un footing, sans être une séance : respiration marquée mais régulière, "
                      "tu peux encore dire quelques mots.")
    if hilly:
        s["gain_m"] = round(p.get("easy_vam", 0) * (15 + block + 10) / 60 * 0.5, -1)
    return s


def _variations(minutes: float, p: dict) -> list[dict]:
    """Sortie longue sur le plat avec variations d'allure : environ 60 % de l'endurance d'abord (20 min
    au moins), des blocs de 6 min soutenus séparés de 4 min en endurance, le reste de l'endurance,
    puis 10 min de retour au calme ; à allure semi ou marathon pour ces courses."""
    reps = int(min(5, max(2, (minutes - 40) // 20)))
    easy = minutes - reps * 6 - (reps - 1) * 4 - COOLDOWN_MIN
    while easy < 20 and reps > 1:
        reps -= 1
        easy = minutes - reps * 6 - (reps - 1) * 4 - COOLDOWN_MIN
    first = max(20, round5(easy * 0.6))
    rest = max(0.0, easy - first)
    race = p.get("race_kind") in ("semi", "marathon") and p.get("race")
    what = f"à allure {RACE_NAMES[p['race_kind']]}" if race else "en allure soutenue"
    work = (target_info(RACE_ROAD, p, pace_s=p["race"], band=0.01) if race else target_info(STEADY, p))
    dist = f", environ {round(first * 60 / p['easy'])} km" if p.get("easy") else ""
    steps = [step("steady", f"{_minutes(first)} en endurance{dist}", first,
                  target_info(EASY, p, _easy_pace(p))),
             step("work", f"{reps} × 6 min {what}", reps * 6, work),
             step("recovery", "4 min en endurance entre les blocs, sans s'arrêter", (reps - 1) * 4,
                  target_info(EASY, p))]
    if rest >= 5:
        steps.append(step("steady", f"{_minutes(rest)} en endurance", rest,
                          target_info(EASY, p, _easy_pace(p))))
    steps.append(_cooldown(cool(), p))
    return steps


def long_run(variant: str, minutes: float, p: dict, km: bool = True, steady_finish: bool = False) -> dict:
    """Sortie longue : classique, progressive, vallonnée, spécifique trail, avec descentes, ou sur
    le plat avec variations d'allure. Le D+ d'une sortie en endurance suit la vitesse de montée du
    coureur en endurance (easy_vam), pas celle de la course. Fin soutenue (steady_finish) : sur le
    plat, le bloc finit la sortie avant 10 min de retour au calme ; en terrain vallonné, il se place
    au milieu, pour redescendre ensuite en endurance."""
    gain = round(p.get("easy_vam", 0) * minutes / 60, -1)
    if steady_finish and variant not in ("progressive", "spécifique", "variations"):
        block = steady_finish_min(minutes)
        if variant in ("vallonnée", "descentes") or not km:
            first = round5((minutes - block) * 0.45)
            second = minutes - block - first
            up = _gain_text(round(gain * 0.45, -1))
            steps = [step("steady", f"{_minutes(first)} en endurance sur sentier{up}", first,
                          target_info(EASY, p)),
                     step("work", f"au milieu, {block} min en allure soutenue sur une portion roulante ou en "
                                  "montée douce", block, target_info(STEADY, p)),
                     step("steady", f"{_minutes(second)} en endurance pour revenir, descentes relâchées",
                          second, target_info(EASY, p))]
            s = _easy_session("sortie longue", "Sortie longue vallonnée et bloc soutenu", steps,
                              f"Le bloc soutenu au milieu, pour revenir en endurance ({WALK}) et finir au "
                              "calme, cuisses ménagées dans les descentes.")
            s["gain_m"] = gain
            return s
        steps = easy_steps(minutes - block - COOLDOWN_MIN, p, km) + [
            step("work", f"{block} min en allure soutenue, sur le plat", block, target_info(STEADY, p)),
            _cooldown(cool(), p)]
        return _easy_session("sortie longue", "Sortie longue et fin soutenue", steps,
                             "Accélérer en fin de sortie, sans forcer : apprendre à courir vite fatigué ; "
                             "puis 10 min au calme.")
    if variant == "progressive":
        end = steady_finish_min(minutes)
        steps = easy_steps(minutes - end - COOLDOWN_MIN, p, km) + [
            step("work", f"{end} min en allure soutenue", end, target_info(STEADY, p)), _cooldown(cool(), p)]
        return _easy_session("sortie longue", "Sortie longue progressive", steps,
                             "Finir plus vite qu'au départ, sans jamais forcer : apprendre à accélérer "
                             "fatigué, puis 10 min au calme.")
    if variant == "variations":
        s = _easy_session("sortie longue", "Sortie longue sur le plat, variations d'allure",
                          _variations(minutes, p),
                          "Sur un parcours plat et roulant : les changements d'allure rompent la monotonie "
                          "et apprennent à relancer.")
        s["flat"] = True
        return s
    if variant == "vallonnée":
        steps = [step("steady", f"{_minutes(minutes)} en endurance sur sentier{_gain_text(gain)}", minutes,
                      target_info(EASY, p))]
        s = _easy_session("sortie longue", "Sortie longue vallonnée", steps,
                          f"Le D+ correspond à ta vitesse de montée habituelle en endurance : {WALK}.")
        s["gain_m"] = gain
        return s
    if variant == "spécifique":
        climb = 15 if minutes < 100 else 20
        first = round5((minutes - climb) * 0.4)
        rest = minutes - climb - first
        steps = [step("steady", f"{_minutes(first)} en endurance sur sentier", first, target_info(EASY, p)),
                 step("work", f"au milieu, une montée de {climb} min à l'effort de course", climb,
                      target_info(RACE_TRAIL, p)),
                 step("steady", f"{_minutes(rest)} en endurance pour revenir"
                      f"{_gain_text(round(gain * 0.8, -1))} au total", rest, target_info(EASY, p))]
        s = _easy_session("sortie longue", "Sortie longue spécifique", steps,
                          f"Le reste du temps en endurance ({WALK}) ; descentes relâchées, pour garder "
                          "des cuisses pour la fin de course.")
        s["gain_m"] = round(gain * 0.8 + climb / 60 * p.get("easy_vam", 0) * CLIMB_EFFORT_FACTOR, -1)
        return s
    if variant == "descentes":
        steps = [step("steady", f"{_minutes(minutes)} en endurance sur sentier{_gain_text(gain)}", minutes,
                      target_info(EASY, p)),
                 step("work", "dans 3 ou 4 descentes, 2 à 3 min plus vite, relâché", 0, target_info(DOWN, p))]
        s = _easy_session("sortie longue", "Sortie longue avec descentes", steps,
                          f"En endurance le reste du temps ({WALK}) ; travailler les descentes sans "
                          "se faire mal.")
        s["gain_m"] = gain
        return s
    return _easy_session("sortie longue", "Sortie longue", easy_steps(minutes, p, km),
                         "Régulière du début à la fin, en aisance respiratoire.")


# ---------- charge estimée d'une séance ----------

DEFAULT_RATES = {"easy": 60.0, "steady": 72.5, "quality": 85.0}   # HRSS par heure, à défaut


def estimated_load(s: dict, rates: dict | None) -> float:
    """Charge prévue d'une séance (HRSS) : séance dure à la charge par heure des séances du coureur ;
    sinon en endurance, sauf ses étapes d'effort (bloc soutenu, lignes droites), à la charge par
    heure des sorties soutenues ou des séances."""
    rates = rates or DEFAULT_RATES
    minutes = s.get("minutes") or 0
    if s.get("hard"):
        return minutes * rates["quality"] / 60
    work = sum(x["minutes"] for x in s.get("steps", []) if x["kind"] == "work")
    steady_like = s.get("type") in ("footing soutenu", "sortie longue")
    work_rate = rates.get("steady", rates["quality"]) if steady_like else rates["quality"]
    return ((minutes - work) * rates["easy"] + work * work_rate) / 60


# ---------- catalogue et rotation ----------

def _q(make, shift: int = 0, mult: int = 1):
    """Créneau du catalogue : palier = tour × mult + shift (mult 2 : deux créneaux d'un même type
    dans la rotation, qui montent chacun leur tour)."""
    return lambda lv, p, compact=False: make(lv * mult + shift, p, compact)


# séance clé par phase, route ou trail : les variantes tournent d'une semaine de charge à l'autre (un
# tour complet avant toute répétition), le palier monte à chaque tour. Entonnoir du général au
# spécifique : foncier (endurance, force, vitesse légère : côtes courtes, sprints, fartlek), puis
# développement (seuil et VMA, dosés selon la course), puis spécifique (allure de course en blocs
# qui s'allongent, une semaine sur deux, entre des séances de soutien)
QUALITY = {
    ("foncier", False): [_q(fartlek), _q(hills_short), _q(vma), _q(pyramid)],
    ("foncier", True): [_q(hills_short), _q(fartlek), _q(power_hike), _q(vma), _q(pyramid)],
    ("développement", False): [_q(seuil), _q(vma, 2), _q(tempo), _q(pyramid, 1), _q(hills_medium)],
    ("développement", True): [_q(seuil), _q(hills_medium), _q(vma, 2), _q(uphill_tempo), _q(pyramid, 1),
                              _q(tempo)],
    ("spécifique", False): [_q(race_pace, 0, 2), _q(seuil, 2), _q(race_pace, 1, 2), _q(tempo, 1)],
    ("spécifique", True): [_q(hills_long), _q(uphill_tempo, 1), _q(downhill), _q(seuil, 2),
                           _q(power_hike, 1), _q(hills_medium, 1)],
    # maintien de forme (étape 7) : une séance de qualité qui varie, seuil, fractionné, côtes
    ("maintien", False): [_q(seuil), _q(fartlek), _q(vma, 2), _q(hills_short), _q(tempo), _q(pyramid)],
    ("maintien", True): [_q(hills_short), _q(seuil), _q(hills_medium), _q(fartlek), _q(uphill_tempo),
                         _q(vma)],
    # reprise : de l'intensité courte et légère, le volume revient d'abord
    ("reprise", False): [_q(fartlek), _q(hill_sprints)],
    ("reprise", True): [_q(hill_sprints), _q(fartlek)],
    # orientations sans course (étape 8) : vitesse (10 km et moins), route longue (semi, marathon), trail
    ("vitesse", False): [_q(vma), _q(seuil), _q(pyramid, 1), _q(fartlek, 1), _q(vma, 2), _q(tempo)],
    ("route longue", False): [_q(seuil), _q(tempo), _q(seuil, 2), _q(tempo, 1), _q(vma, 2)],
    ("trail", True): [_q(hills_short), _q(uphill_tempo), _q(hills_medium), _q(power_hike), _q(downhill),
                      _q(seuil)],
}
# selon la course sur route : plus de VMA pour 5 et 10 km, plus de seuil et de tempo pour le semi et
# le marathon ; en spécifique, l'allure de course une semaine sur deux, des séances de soutien entre
BY_RACE = {
    ("développement", "5k"): [_q(vma, 2), _q(seuil), _q(pyramid, 1), _q(vma, 3), _q(hills_medium)],
    ("développement", "10k"): [_q(vma, 2), _q(seuil), _q(pyramid, 1), _q(tempo), _q(vma, 3)],
    ("développement", "semi"): [_q(seuil), _q(tempo), _q(vma, 2), _q(seuil, 1), _q(pyramid, 1)],
    ("développement", "marathon"): [_q(tempo), _q(seuil), _q(tempo, 1), _q(vma, 2), _q(seuil, 1)],
    ("spécifique", "5k"): [_q(race_pace, 0, 2), _q(vma, 3), _q(race_pace, 1, 2), _q(seuil, 2)],
    ("spécifique", "10k"): [_q(race_pace, 0, 2), _q(vma, 3), _q(race_pace, 1, 2), _q(seuil, 2)],
    ("spécifique", "semi"): [_q(race_pace, 0, 2), _q(seuil, 2), _q(race_pace, 1, 2), _q(tempo, 1)],
    ("spécifique", "marathon"): [_q(race_pace, 0, 2), _q(tempo, 1), _q(race_pace, 1, 2), _q(seuil, 2)],
}
# nuance d'une préparation (« plus de côtes », « plus de vitesse ») : une semaine de charge sur deux,
# la séance clé devient une séance de ce type, adaptée à la phase
NUANCE = {"côtes": {"foncier": _q(hills_short), "développement": _q(hills_medium),
                    "spécifique": _q(hills_long)},
          "vitesse": {"foncier": _q(fartlek), "développement": _q(vma), "spécifique": _q(vma, 2)}}
SECOND = [_q(vma), _q(seuil, 2)]
LIGHT = [_q(hill_sprints), _q(fartlek)]
# sorties longues : en trail, une sur le plat avec variations d'allure de temps en temps (hors phase
# spécifique, où le terrain de la course prime)
LONG = {("foncier", False): ["classique", "variations"],
        ("développement", False): ["classique", "progressive", "variations"],
        ("spécifique", False): ["progressive", "variations", "classique"],
        ("foncier", True): ["vallonnée", "variations"], ("développement", True): ["vallonnée", "variations",
                                                                                  "descentes"],
        ("spécifique", True): ["spécifique", "vallonnée", "descentes"],
        ("maintien", False): ["classique", "progressive", "variations"],
        ("maintien", True): ["vallonnée", "variations", "descentes"],
        ("reprise", False): ["classique"], ("reprise", True): ["vallonnée"],
        ("vitesse", False): ["classique", "variations"],
        ("route longue", False): ["progressive", "variations", "classique"],
        ("trail", True): ["vallonnée", "variations", "descentes", "spécifique"]}
DOWNHILL_TYPES = ("descente",)


def options_for(phase: str, trail: bool, race_kind: str | None = None) -> list:
    if not trail and (phase, race_kind) in BY_RACE:
        return BY_RACE[(phase, race_kind)]
    return QUALITY[(phase, trail)]


def rotate(options: list, week_in_phase: int, shift: int = 0):
    """Variante de la semaine et palier : la variante change chaque semaine, le palier monte à
    chaque tour complet des variantes."""
    i = week_in_phase + shift
    return options[i % len(options)], i // len(options)


def quality(phase: str, kind: str, rank: int, trail: bool, week_in_phase: int, p: dict,
            day_max: float, nuance: str | None = None, no_downhill: bool = False) -> dict:
    """Séance de qualité du créneau `rank` (0 : la séance clé), tournante, ramenée au temps du jour ;
    nuance du coureur une semaine de charge sur deux ; no_downhill : pas de descente travaillée
    (dernières semaines avant la course), la variante suivante la remplace."""
    if kind in ("affûtage", "course"):
        s = reminder(trail, p)
        return with_gain(s if s["minutes"] <= day_max else reminder(trail, p, compact=True), p)
    if kind == "allégée":
        options = LIGHT
    elif rank == 0 and nuance in NUANCE and phase in NUANCE[nuance] and week_in_phase % 2 == 1:
        return with_gain(fit(lambda lv, compact=False: NUANCE[nuance][phase](lv, p, compact),
                             week_in_phase // 4, day_max), p)
    elif rank == 0:
        options = options_for(phase, trail, p.get("race_kind"))
    else:
        options = SECOND
    for shift in range(len(options)):
        make, level = rotate(options, week_in_phase, shift)
        s = with_gain(fit(lambda lv, compact=False, m=make: m(lv, p, compact), level, day_max), p)
        if not (no_downhill and s["type"] in DOWNHILL_TYPES):
            return s
    return s


def test_run(trail: bool, p: dict) -> dict:
    """Test facultatif du maintien de forme : un repère sans dossard, de temps en temps. Route : 5 km
    à fond, réguliers ; trail : une montée connue chronométrée à l'effort. Le résultat entre dans
    les meilleurs efforts (courbe allure-durée, VAM) sans rien saisir."""
    if trail:
        work = step("work", "une montée connue de 15 à 25 min, chronométrée, à l'effort le plus "
                            "haut que tu peux tenir jusqu'en haut", 20, target_info(VO2, p))
        label, note = "Test en montée", "Toujours la même montée, pour comparer d'une fois sur l'autre."
    else:
        work = step("work", "5 km à fond, réguliers du début à la fin", 25, target_info(VO2, p))
        label, note = "Test sur 5 km", "Sur un parcours plat et connu, pour comparer d'une fois sur l'autre."
    s = _session("test", label, [_warmup(WARMUP_MIN, p), work, _cooldown(COOLDOWN_MIN, p)],
                 "Facultatif : un repère de forme sans dossard. " + note
                 + " Sans envie de test, fais la séance de qualité habituelle à la place.")
    return with_gain(s, p)


def long_variant(phase: str, kind: str, trail: bool, week_in_phase: int, no_downhill: bool = False) -> str:
    if kind in ("affûtage", "course", "allégée"):
        return "vallonnée" if trail else "classique"
    options = LONG[(phase, trail)]
    if no_downhill:
        options = [v for v in options if v != "descentes"] or ["vallonnée"]
    variant, _ = rotate(options, week_in_phase)
    return variant


# ---------- D+ estimé d'une séance ----------

CLIMB_EFFORT_FACTOR = 1.3   # en côte à l'effort, on monte plus vite qu'en endurance (approximation)
CLIMB_STEP = {"côtes": "work", "vma en côte": "work", "côtes longues": "work", "montée au seuil": "work",
              "marche en côte": "work", "rappel": "work", "descente": "recovery"}


def with_gain(s: dict, p: dict) -> dict:
    """Ajoute à une séance de côte son D+ estimé : minutes de montée à l'effort (ou de remontée en
    marchant pour la descente) × vitesse de montée en endurance du coureur × 1,3."""
    kind = CLIMB_STEP.get(s["type"])
    if s["type"] == "rappel" and "côte" not in s["label"]:
        kind = None                                     # rappel d'allure sur route : pas de D+
    if kind and "gain_m" not in s:
        minutes = sum(x["minutes"] for x in s["steps"] if x["kind"] == kind)
        factor = 1.0 if kind == "recovery" else CLIMB_EFFORT_FACTOR
        s["gain_m"] = round(minutes / 60 * p.get("easy_vam", 0) * factor, -1)
    s.setdefault("gain_m", 0)
    return s


# ---------- deux propositions par séance (étape 9) ----------

HILLY = {"côtes", "côtes longues", "vma en côte", "montée au seuil", "marche en côte", "descente",
         "sprints en côte"}


def alternative(phase: str, kind: str, rank: int, trail: bool, week_in_phase: int, p: dict, day_max: float,
                main: dict, no_downhill: bool = False) -> dict | None:
    """Seconde proposition pour une séance de qualité, au même rôle : la variante suivante du
    catalogue de la semaine, sur l'autre terrain si possible (côtes contre plat), sinon simplement
    d'un autre type. Aucune en semaine d'affûtage ou de course (le rappel est la séance)."""
    if kind in ("affûtage", "course"):
        return None
    if kind == "allégée":
        options = LIGHT
    elif rank == 0:
        options = options_for(phase, trail, p.get("race_kind"))
    else:
        options = SECOND
    hilly = main["type"] in HILLY
    candidates = []
    for shift in range(1, len(options)):
        make, level = rotate(options, week_in_phase, shift)
        s = with_gain(fit(lambda lv, compact=False, m=make: m(lv, p, compact), level, day_max), p)
        if s["type"] != main["type"] and not (no_downhill and s["type"] in DOWNHILL_TYPES):
            candidates.append(s)
    if not candidates:
        return None
    other = [s for s in candidates if (s["type"] in HILLY) != hilly]
    return (other or candidates)[0]


def same_load(make, minutes: float, goal: float, rates: dict | None) -> dict:
    """Séance faite par make(minutes), raccourcie par pas de 5 min jusqu'à ne pas dépasser la charge
    visée (la séance d'origine) ; au moins 30 min."""
    m = floor5(minutes)
    s = make(m)
    while m > 30 and estimated_load(s, rates) > goal + 1:
        m -= 5
        s = make(m)
    return s


def long_alternative(phase: str, kind: str, trail: bool, week_in_phase: int, variant: str, minutes: float,
                     p: dict, km: bool, main: dict | None = None, rates: dict | None = None) -> dict | None:
    """Seconde proposition pour la sortie longue. Sortie en terrain vallonné : la même charge estimée
    sur le plat, avec variations d'allure (neige, boue, pas de dénivelé à portée). Sinon une autre
    variante de la phase (ou, à défaut, progressive sur route, vallonnée en trail), même durée."""
    hilly = variant in ("vallonnée", "descentes", "spécifique") or (main is not None and main.get("gain_m"))
    if hilly:
        goal = estimated_load(main or long_run(variant, minutes, p, km), rates)
        s = same_load(lambda m: long_run("variations", m, p), minutes, goal, rates)
        s["description"] = ("Sur le plat, à la même charge estimée que la sortie vallonnée : quand la neige "
                            "ou la boue empêchent le dénivelé. " + s["description"])
        return s
    phase_key = (phase, trail) if (phase, trail) in LONG else None
    options = list(LONG[phase_key]) if phase_key else []
    options += ["vallonnée", "descentes"] if trail else ["progressive", "classique"]
    other = next((v for v in options if v != variant), None)
    return long_run(other, minutes, p, km and other != "vallonnée") if other else None


def easy_alternative(s: dict, p: dict) -> dict:
    """Seconde proposition pour un footing : vallonné au lieu du plat, ou l'inverse, même durée."""
    hilly = s["type"] == "footing vallonné"
    return easy_run(s["minutes"], p, not hilly, km=hilly)


# ---------- bibliothèque de séances (étape 9) ----------

def library(p: dict, rates: dict | None = None) -> list[dict]:
    """Toutes les séances du coach par famille, au premier palier et au plus haut, avec les allures
    et la FC du coureur et leur charge estimée : pour choisir, remplacer ou simplement s'inspirer."""
    def both(make):
        first, last = make(0, p), make(9, p)
        same = last["label"] == first["label"] and last["minutes"] == first["minutes"]
        return [first] if same else [first, last]
    specific = []
    for kind in SPECIFIC:
        q = {**p, "race_kind": kind, "race": p.get("race") or ((p.get("vma") or DEFAULT_VMA_PACE)
                                                                / {"5k": 0.95, "10k": 0.9, "semi": 0.85,
                                                                   "marathon": 0.8}[kind])}
        specific += [race_pace(0, q), race_pace(9, q)]
    out = [
        {"family": "Endurance", "why": "La base : 80 % du temps, en aisance respiratoire.",
         "sessions": [easy_run(45, p, False), easy_run(50, p, True), steady_run(50, p), strides(45, p)]},
        {"family": "Sorties longues",
         "why": "L'endurance pour durer ; une fin rapide apprend à accélérer fatigué.",
         "sessions": [long_run("classique", 90, p), long_run("progressive", 90, p),
                      long_run("classique", 90, p, steady_finish=True), long_run("variations", 90, p),
                      long_run("vallonnée", 100, p, km=False),
                      long_run("vallonnée", 100, p, km=False, steady_finish=True),
                      long_run("descentes", 100, p, km=False), long_run("spécifique", 110, p, km=False)]},
        {"family": "Fartlek et pyramide", "why": "Des changements d'allure au feeling, pour varier.",
         "sessions": both(fartlek) + both(pyramid)},
        {"family": "Seuil et tempo",
         "why": "L'allure qu'on tiendrait une heure : le moteur des courses longues.",
         "sessions": both(seuil) + both(tempo)},
        {"family": "VMA", "why": "Courtes et vives : la vitesse maximale aérobie, pour le 10 km et moins. "
                                 "Plus la fraction est courte, plus l'allure est vive.",
         "sessions": both(vma)},
        {"family": "Côtes", "why": "Force et puissance, et le terrain des trails.",
         "sessions": [with_gain(s, p) for s in both(hill_sprints) + both(hills_short) + both(hills_medium)
                      + both(hills_long)]},
        {"family": "Trail", "why": "Monter longtemps, marcher vite, descendre sans se faire mal.",
         "sessions": [with_gain(s, p) for s in both(uphill_tempo) + both(power_hike) + both(downhill)]},
        {"family": "Allure spécifique",
         "why": "L'allure du jour J en blocs qui s'allongent au fil de la phase spécifique, selon la course "
                "(allure d'exemple quand aucune course n'est prévue).",
         "sessions": specific},
        {"family": "Tests", "why": "Un repère de forme sans dossard.",
         "sessions": [test_run(False, p), test_run(True, p)]},
    ]
    for f in out:
        for s in f["sessions"]:
            s["load"] = round(estimated_load(s, rates))
    return out
