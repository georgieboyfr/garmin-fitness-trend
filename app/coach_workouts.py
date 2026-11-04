"""
Bibliothèque de séances du coach : séances structurées en étapes (échauffement, effort répété,
récupération, retour au calme), chacune avec sa cible : allure en plage, FC en plage (en % de la
LTHR, zones de Friel) et effort perçu (échelle de 1 à 10), utile en trail où l'allure ne veut
rien dire. Paliers de progression ; durée totale tirée de la structure, arrondie à 5 min.

Formats classiques de l'entraînement en course à pied (seuil en blocs, VMA en 30/30 ou en
fractions de 400 à 1 000 m, côtes courtes et longues, allure spécifique), rédigés pour ce projet.
Inspirations : présentation des séances de time-to-run (MIT), étapes typées avec répétitions et
cibles en plage d'OpenAthlete (idée seulement, aucun code repris).
"""
import math

ROUND_MIN = 5
WARMUP_MIN = 15
COOLDOWN_MIN = 10
DEFAULT_VMA_PACE = 270.0           # s/km, à défaut d'estimation (4:30 /km)
PACE_BAND = 0.02                   # plage d'allure : ±2 %
# cibles en % de la LTHR (zones de Friel) et effort perçu (1 à 10)
EASY = {"hr": (None, 0.90), "rpe": "3 à 4"}
THRESHOLD = {"hr": (0.95, 1.00), "rpe": "7"}
VO2 = {"hr": (1.00, None), "rpe": "9"}
HILL_SHORT = {"hr": None, "rpe": "8 à 9"}
RACE_TRAIL = {"hr": (0.90, 1.00), "rpe": "6 à 7"}
RECOVERY = {"hr": None, "rpe": "2"}


def warm(compact: bool, normal: float = WARMUP_MIN) -> float:
    return 10 if compact else normal


def cool(compact: bool) -> float:
    return 5 if compact else COOLDOWN_MIN


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


def target(intensity: dict, lthr: float | None, pace: str = "") -> str:
    """Cible lisible : allure, FC en plage, effort perçu."""
    parts = [pace] if pace else []
    hr = intensity.get("hr")
    if hr and lthr:
        low, high = hr
        if low and high:
            parts.append(f"FC {round(low * lthr)} à {round(high * lthr)}")
        elif high:
            parts.append(f"FC sous {round(high * lthr)}")
        else:
            parts.append(f"FC au-dessus de {round(low * lthr)}")
    parts.append(f"effort {intensity['rpe']}/10")
    return " · ".join(parts)


def step(kind: str, text: str, minutes: float, cible: str = "") -> dict:
    """Étape : warmup, work (effort, répété ou non), recovery, cooldown, steady."""
    return {"kind": kind, "text": text, "minutes": minutes, "target": cible}


def _session(type_: str, label: str, steps: list[dict], note: str = "") -> dict:
    total = sum(s["minutes"] for s in steps)
    return {"type": type_, "label": label, "minutes": round5(total), "steps": steps, "description": note,
            "hard": True}


def _warmup(minutes: float, lthr) -> dict:
    return step("warmup", f"Échauffement {_minutes(minutes)} en endurance", minutes, target(EASY, lthr))


def _cooldown(minutes: float, lthr) -> dict:
    return step("cooldown", f"Retour au calme {_minutes(minutes)} au trot", minutes, target(EASY, lthr))


# paliers : (répétitions, durée en min, récupération en min)
SEUIL = [(3, 8, 2), (3, 10, 2), (2, 15, 3), (4, 10, 2), (3, 12, 3), (2, 20, 4)]
VMA = [("30/30", 10), ("30/30", 12), ("m", 8, 400), ("m", 6, 600), ("m", 5, 800), ("m", 4, 1000)]
COTES_COURTES = [8, 10, 12]                        # × 30 s
COTES_LONGUES = [(4, 4), (5, 4), (4, 5), (3, 8)]   # × min de montée
ALLURE = [(3, 10, 3), (3, 12, 3), (2, 20, 4), (3, 15, 3)]
VMA_REST = {400: 1.5, 600: 2.0, 800: 2.5, 1000: 3.0}   # récupération au trot, min


def seuil(level: int, p: dict, compact: bool = False) -> dict:
    reps, work, rest = SEUIL[min(level, len(SEUIL) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × {work} min au seuil", reps * work,
                  target(THRESHOLD, lthr, pace_band(p.get("threshold")))),
             step("recovery", f"récupération {rest} min au trot entre les blocs", (reps - 1) * rest,
                  target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("seuil", "Seuil", steps, "Allure « confortablement difficile » : on pourrait la tenir "
                                             "une heure. Les blocs doivent rester réguliers.")


def vma(level: int, p: dict, compact: bool = False) -> dict:
    entry = VMA[min(level, len(VMA) - 1)]
    lthr, pace = p.get("lthr"), p.get("vma") or DEFAULT_VMA_PACE
    if entry[0] == "30/30":
        reps = entry[1]
        work = step("work", f"{reps} × 30 s vite / 30 s au trot, sans arrêt", reps * 1.0,
                    target(VO2, lthr, pace_band(p.get("vma"))))
        steps = [_warmup(warm(compact, 20), lthr), work]
    else:
        _, reps, meters = entry
        rest = VMA_REST[meters]
        steps = [_warmup(warm(compact, 20), lthr),
                 step("work", f"{reps} × {meters} m à allure VMA", reps * meters / 1000 * pace / 60,
                      target(VO2, lthr, pace_band(p.get("vma")))),
                 step("recovery", f"récupération {_minutes(rest)} au trot", (reps - 1) * rest,
                      target(RECOVERY, lthr))]
    steps.append(_cooldown(cool(compact), lthr))
    return _session("vma", "VMA", steps, "Vite mais en contrôle : la dernière répétition aussi rapide que "
                                         "la première. Arrêter si l'allure s'effondre.")


def strides(base_min: float, p: dict) -> dict:
    lthr = p.get("lthr")
    steps = [step("steady", f"{_minutes(base_min)} en endurance", base_min,
                  target(EASY, lthr, f"≈ {pace_text(p.get('easy'))} /km" if p.get("easy") else "")),
             step("work", "8 × 20 s en accélération progressive", 8 * 20 / 60,
                  "effort 7 à 8/10, jamais à fond"),
             step("recovery", "récupération 1 min au trot ou en marchant", 7, target(RECOVERY, lthr))]
    s = _session("lignes droites", "Footing et lignes droites", steps,
                 "Les accélérations restent fluides : travail de foulée, pas de fatigue.")
    s["hard"] = False
    return s


def hills_short(level: int, p: dict, compact: bool = False) -> dict:
    reps = COTES_COURTES[min(level, len(COTES_COURTES) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × 30 s de montée vive, pente moyenne", reps * 0.5,
                  target(HILL_SHORT, lthr)),
             step("recovery", "retour en descendant au trot, environ 1 min 30", reps * 1.5,
                  target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("côtes", "Côtes courtes", steps, "Travail de force : genoux hauts, appuis dynamiques, "
                                                     "buste droit.")


def hills_long(level: int, p: dict, compact: bool = False) -> dict:
    reps, work = COTES_LONGUES[min(level, len(COTES_LONGUES) - 1)]
    rest = round(work * 0.75, 1)
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × {work} min de montée", reps * work, target(THRESHOLD, lthr)),
             step("recovery", f"redescente au trot, environ {_minutes(rest)}", reps * rest,
                  target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("côtes longues", "Côtes longues", steps,
                    "À l'effort du seuil, pas à l'allure : en côte, la FC et la sensation guident. En "
                    "descente, relâché et pieds légers, c'est aussi un entraînement.")


def race_pace(level: int, p: dict, compact: bool = False) -> dict:
    reps, work, rest = ALLURE[min(level, len(ALLURE) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × {work} min à allure course", reps * work,
                  target({"hr": None, "rpe": "6 à 7"}, lthr, pace_band(p.get("race"), 0.01))),
             step("recovery", f"récupération {rest} min au trot", (reps - 1) * rest, target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("allure course", "Allure course", steps,
                    "Mémoriser les sensations de l'allure du jour J.")


def reminder(trail: bool, p: dict, compact: bool = False) -> dict:
    lthr = p.get("lthr")
    if trail:
        steps = [_warmup(warm(compact, 20), lthr),
                 step("work", "3 × 3 min de montée à l'effort de course", 9, target(RACE_TRAIL, lthr)),
                 step("recovery", "redescente souple au trot", 7.5, target(RECOVERY, lthr)),
                 _cooldown(cool(compact), lthr)]
        return _session("rappel", "Rappel en côte", steps, "Retrouver les sensations du terrain sans se "
                                                           "fatiguer.")
    steps = [_warmup(warm(compact, 20), lthr),
             step("work", "3 × 3 min à allure course", 9,
                  target({"hr": None, "rpe": "6 à 7"}, lthr, pace_band(p.get("race"), 0.01))),
             step("recovery", "récupération 2 min au trot", 4, target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("rappel", "Rappel d'allure", steps, "Garder le rythme sans se fatiguer.")


def easy_steps(minutes: float, p: dict, km: bool = True) -> list[dict]:
    """Footing ou sortie longue : une seule étape, en endurance."""
    pace = p.get("easy")
    dist = f", environ {round(minutes * 60 / pace)} km sur le plat" if km and pace else ""
    return [step("steady", f"{_minutes(minutes)} en endurance fondamentale{dist}", minutes,
                 target(EASY, p.get("lthr"), f"≈ {pace_text(pace)} /km" if pace and km else ""))]


def fit(make, level: int, day_max: float) -> dict:
    """Palier le plus haut, jusqu'à `level`, dont la durée tient dans le temps du jour ; à défaut,
    le premier palier avec un échauffement et un retour au calme raccourcis."""
    for lv in range(level, -1, -1):
        s = make(lv)
        if s["minutes"] <= day_max:
            return s
    return make(0, compact=True)
