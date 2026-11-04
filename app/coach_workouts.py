"""
Bibliothèque de séances du coach : séances structurées en étapes (échauffement, effort répété,
récupération, retour au calme), chacune avec sa cible : allure en plage, FC en plage (en % de la
LTHR, zones de Friel) et effort perçu (échelle de 1 à 10), utile en trail où l'allure ne veut
rien dire. Paliers de progression ; durée totale tirée de la structure, arrondie à 5 min.

Formats classiques de l'entraînement en course à pied (seuil en blocs, VMA en 30/30 ou en
fractions de 400 à 1 000 m, côtes courtes et longues, allure spécifique), rédigés pour ce projet.
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


PYRAMIDE = [(1, 2, 3, 2, 1), (1, 2, 3, 4, 3, 2, 1), (2, 3, 4, 4, 3, 2)]   # min d'effort


def pyramid(level: int, p: dict, compact: bool = False) -> dict:
    """Pyramide : efforts de 1 à 4 min qui montent puis redescendent, entre l'allure 5 km et le
    seuil, récupération au trot de la moitié de l'effort précédent."""
    blocks = PYRAMIDE[min(level, len(PYRAMIDE) - 1)]
    lthr = p.get("lthr")
    pace = pace_band(p["threshold"] * 0.96) if p.get("threshold") else ""
    work = sum(blocks)
    rest = sum(b / 2 for b in blocks[:-1])
    steps = [_warmup(warm(compact, 20), lthr),
             step("work", "pyramide " + "-".join(str(b) for b in blocks) + " min, vite mais régulier", work,
                  target({"hr": (0.97, 1.03), "rpe": "7 à 8"}, lthr, pace)),
             step("recovery", "récupération au trot : la moitié de l'effort qui précède (30 s après 1 min, "
                              "1 min après 2 min...)", rest, target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("pyramide", "Pyramide", steps, "Partir prudemment : les efforts longs du milieu se "
                                                   "courent à la même allure que les courts.")


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
             step("recovery", "récupération : redescente au trot, 1 min 30 (3 fois l'effort)", reps * 1.5,
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
             step("recovery", f"récupération : redescente au trot, environ {_minutes(rest)}, repartir dès "
                              "que le souffle est revenu", reps * rest,
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
                 step("recovery", "récupération : redescente souple au trot, environ 2 min 30 après "
                      "chaque montée", 7.5, target(RECOVERY, lthr)),
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


# ---------- séances supplémentaires (variété) ----------

TEMPO = [20, 25, 30, 35]                          # min en continu
FARTLEK = [8, 10, 12]                             # × 1 min vif / 1 min footing
HILL_SPRINTS = [6, 8, 10]                         # × 10 s
HILLS_MEDIUM = [6, 8, 10]                         # × 1 min
UPHILL_TEMPO = [15, 20, 25, 30]                   # min de montée continue
POWER_HIKE = [(4, 4), (5, 4), (4, 6), (5, 6)]     # × min de marche rapide
DOWNHILL = [4, 6, 8]                              # × 1 min 30 de descente
STEADY = {"hr": (0.90, 0.95), "rpe": "5 à 6"}     # zone 3 : soutenu mais confortable
WALK = "marcher dans les montées raides pour rester sous la FC visée"


def steady_finish_min(minutes: float) -> int:
    """Durée de la fin soutenue d'une sortie longue."""
    return 15 if minutes < 90 else 20


def tempo(level: int, p: dict, compact: bool = False) -> dict:
    minutes = TEMPO[min(level, len(TEMPO) - 1)]
    lthr = p.get("lthr")
    pace = pace_band(p["threshold"] * 1.04) if p.get("threshold") else ""
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{minutes} min en continu, allure soutenue", minutes, target(STEADY, lthr, pace)),
             _cooldown(cool(compact), lthr)]
    return _session("tempo", "Tempo", steps, "Un cran sous le seuil : soutenu mais régulier, la respiration "
                                             "rythmée sans être haletante.")


def fartlek(level: int, p: dict, compact: bool = False) -> dict:
    reps = FARTLEK[min(level, len(FARTLEK) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × 1 min vif", reps, target({"hr": None, "rpe": "7 à 8"}, lthr)),
             step("recovery", "récupération 1 min en footing, sans s'arrêter", reps - 1, target(EASY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("fartlek", "Fartlek", steps, "Au gré du terrain : les accélérations à la sensation, "
                                                 "plus vite que le seuil, moins vite qu'un sprint.")


def hill_sprints(level: int, p: dict, compact: bool = False) -> dict:
    reps = HILL_SPRINTS[min(level, len(HILL_SPRINTS) - 1)]
    lthr = p.get("lthr")
    base = 10 if compact else 25
    steps = [step("steady", f"{base} min de footing", base, target(EASY, lthr)),
             step("work", f"{reps} × 10 s de sprint en côte raide", reps * 10 / 60,
                  "effort 9/10, très court"),
             step("recovery", "récupération complète : redescente en marchant, 1 min 30", (reps - 1) * 1.5,
                  target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    s = _session("sprints en côte", "Footing et sprints en côte", steps,
                 "Puissance et foulée sans fatigue : l'effort est trop court pour faire monter la FC.")
    s["hard"] = False
    return s


def hills_medium(level: int, p: dict, compact: bool = False) -> dict:
    reps = HILLS_MEDIUM[min(level, len(HILLS_MEDIUM) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × 1 min de montée vive", reps, target({"hr": None, "rpe": "8 à 9"}, lthr)),
             step("recovery", "récupération : redescente au trot, 2 min", reps * 2, target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("vma en côte", "VMA en côte", steps, "Pente moyenne (5 à 8 %) : monter vite en restant "
                                                         "relâché, la même vitesse à chaque répétition.")


def uphill_tempo(level: int, p: dict, compact: bool = False) -> dict:
    minutes = UPHILL_TEMPO[min(level, len(UPHILL_TEMPO) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{minutes} min de montée continue", minutes, target(THRESHOLD, lthr)),
             step("recovery", f"redescente souple au trot, sans forcer, environ {_minutes(minutes * 0.6)}",
                  minutes * 0.6,
                  target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("montée au seuil", "Montée continue au seuil", steps,
                    "Une longue montée à l'effort du seuil, en courant ou en marchant vite selon la pente. "
                    "Sans montée assez longue, enchaîner les côtes du coin sans pause, au même effort.")


def power_hike(level: int, p: dict, compact: bool = False) -> dict:
    reps, work = POWER_HIKE[min(level, len(POWER_HIKE) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact), lthr),
             step("work", f"{reps} × {work} min de marche rapide en forte pente (plus de 15 %)", reps * work,
                  target({"hr": (0.85, 0.95), "rpe": "6"}, lthr)),
             step("recovery", f"récupération : redescente au trot, environ {_minutes(work * 0.6)}",
                  reps * work * 0.6, target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("marche en côte", "Marche rapide en côte", steps,
                    "Mains sur les cuisses ou bâtons, buste penché, pas courts et rapides : la marche "
                    "efficace des fortes pentes de course.")


def downhill(level: int, p: dict, compact: bool = False) -> dict:
    reps = DOWNHILL[min(level, len(DOWNHILL) - 1)]
    lthr = p.get("lthr")
    steps = [_warmup(warm(compact, 20), lthr),
             step("work", f"{reps} × 1 min 30 de descente rapide sur sentier", reps * 1.5,
                  target({"hr": None, "rpe": "5 à 6"}, lthr)),
             step("recovery", "récupération : remontée en marchant, environ 3 min", reps * 3,
                  target(RECOVERY, lthr)),
             _cooldown(cool(compact), lthr)]
    return _session("descente", "Descente travaillée", steps,
                    "Foulée courte et rapide, regard loin devant, relâché. Les cuisses travaillent beaucoup "
                    "en descente : commencer avec peu de répétitions.")


# ---------- footings et sorties longues ----------

def _easy_session(type_: str, label: str, steps: list[dict], note: str) -> dict:
    s = _session(type_, label, steps, note)
    s["hard"] = False
    return s


def _gain_text(gain: float) -> str:
    return f", environ {gain:.0f} m de D+" if gain else ""


def easy_run(minutes: float, p: dict, hilly: bool, km: bool = True) -> dict:
    """Footing, sur le plat ou vallonné (moitié de la vitesse de montée en endurance)."""
    lthr = p.get("lthr")
    if hilly:
        gain = round(p.get("easy_vam", 0) * minutes / 60 * 0.5, -1)
        text = f"{_minutes(minutes)} en endurance sur un parcours vallonné{_gain_text(gain)}"
        s = _easy_session("footing vallonné", "Footing vallonné", [step("steady", text, minutes,
                          target(EASY, lthr))], f"Il faut {WALK} : c'est voulu.")
        s["gain_m"] = gain
        return s
    return _easy_session("footing", "Footing", easy_steps(minutes, p, km),
                         "En aisance respiratoire : tu peux parler.")


def steady_run(minutes: float, p: dict, hilly: bool = False) -> dict:
    """Sortie soutenue (endurance active, zone 3) : 15 min faciles, un bloc soutenu, 5 min de retour
    au calme ; plus chargée qu'un footing, moins qu'une séance (ni récupération ni répétitions)."""
    lthr = p.get("lthr")
    block = max(15, round5(minutes - 20))
    where = "sur un parcours vallonné, l'effort plutôt que l'allure" if hilly else "sur le plat"
    steps = [step("warmup", "15 min en endurance", 15, target(EASY, lthr)),
             step("work", f"{block} min en allure soutenue, {where}", block, target(STEADY, lthr)),
             step("cooldown", "5 min au trot", 5, target(EASY, lthr))]
    s = _easy_session("footing soutenu", "Sortie soutenue", steps,
                      "Plus vite qu'un footing, sans être une séance : respiration marquée mais régulière, "
                      "tu peux encore dire quelques mots.")
    if hilly:
        s["gain_m"] = round(p.get("easy_vam", 0) * (15 + block + 5) / 60 * 0.5, -1)
    return s


def long_run(variant: str, minutes: float, p: dict, km: bool = True, steady_finish: bool = False) -> dict:
    """Sortie longue : classique, progressive, vallonnée, spécifique trail ou avec descentes. Le D+
    d'une sortie en endurance suit la vitesse de montée du coureur en endurance (easy_vam), pas
    celle de la course."""
    lthr = p.get("lthr")
    gain = round(p.get("easy_vam", 0) * minutes / 60, -1)
    if steady_finish and variant not in ("progressive", "spécifique"):
        s = long_run(variant, minutes - steady_finish_min(minutes), p, km)
        end = steady_finish_min(minutes)
        where = "sur une portion roulante ou en montée douce" if not km else "sur le plat"
        s["steps"].append(step("work", f"{end} min finales en allure soutenue, {where}", end,
                               target(STEADY, lthr)))
        s["minutes"] = round5(minutes)
        s["label"] += " et fin soutenue"
        s["gain_m"] = round(s.get("gain_m", 0) + gain * end / minutes, -1) if not km else s.get("gain_m", 0)
        s["description"] += " Finir soutenu, sans forcer : apprendre à accélérer fatigué."
        return s
    if variant == "progressive":
        end = 15 if minutes < 90 else 20
        steps = easy_steps(minutes - end, p, km) + [
            step("work", f"{end} min finales en allure soutenue", end, target(STEADY, lthr))]
        return _easy_session("sortie longue", "Sortie longue progressive", steps,
                             "Finir plus vite qu'au départ, sans jamais forcer : apprendre à accélérer "
                             "fatigué.")
    if variant == "vallonnée":
        steps = [step("steady", f"{_minutes(minutes)} en endurance sur sentier{_gain_text(gain)}", minutes,
                      target(EASY, lthr))]
        s = _easy_session("sortie longue", "Sortie longue vallonnée", steps,
                          f"Le D+ correspond à ta vitesse de montée habituelle en endurance : {WALK}.")
        s["gain_m"] = gain
        return s
    if variant == "spécifique":
        climb = 15 if minutes < 100 else 20
        steps = [step("steady", f"{_minutes(minutes - climb)} en endurance sur sentier"
                      f"{_gain_text(round(gain * 0.8, -1))}", minutes - climb, target(EASY, lthr)),
                 step("work", f"au milieu, une montée de {climb} min à l'effort de course", climb,
                      target(RACE_TRAIL, lthr))]
        s = _easy_session("sortie longue", "Sortie longue spécifique", steps,
                          f"Le reste du temps en endurance ({WALK}) ; descentes relâchées, pour garder "
                          "des cuisses pour la fin de course.")
        s["gain_m"] = round(gain * 0.8 + climb / 60 * p.get("easy_vam", 0) * CLIMB_EFFORT_FACTOR, -1)
        return s
    if variant == "descentes":
        steps = [step("steady", f"{_minutes(minutes)} en endurance sur sentier{_gain_text(gain)}", minutes,
                      target(EASY, lthr)),
                 step("work", "dans 3 ou 4 descentes, 2 à 3 min plus vite, relâché", 0,
                      target({"hr": None, "rpe": "5 à 6"}, lthr))]
        s = _easy_session("sortie longue", "Sortie longue avec descentes", steps,
                          f"En endurance le reste du temps ({WALK}) ; travailler les descentes sans "
                          "se faire mal.")
        s["gain_m"] = gain
        return s
    return _easy_session("sortie longue", "Sortie longue", easy_steps(minutes, p, km),
                         "Régulière du début à la fin, en aisance respiratoire.")


# ---------- catalogue et rotation ----------

def _q(make, shift: int = 0):
    return lambda lv, p, compact=False: make(lv + shift, p, compact)


# séance clé par phase, route ou trail : les variantes tournent d'une semaine de charge à l'autre (un
# tour complet avant toute répétition), le palier monte à chaque tour
QUALITY = {
    ("foncier", False): [_q(fartlek), _q(hills_short), _q(vma), _q(pyramid)],
    ("foncier", True): [_q(hills_short), _q(fartlek), _q(power_hike), _q(vma), _q(pyramid)],
    ("développement", False): [_q(seuil), _q(vma, 2), _q(tempo), _q(pyramid, 1), _q(hills_medium)],
    ("développement", True): [_q(seuil), _q(hills_medium), _q(vma, 2), _q(uphill_tempo), _q(pyramid, 1),
                              _q(tempo)],
    ("spécifique", False): [_q(race_pace), _q(seuil, 2), _q(tempo, 1), _q(vma, 3)],
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
# nuance d'une préparation (« plus de côtes », « plus de vitesse ») : une semaine de charge sur deux,
# la séance clé devient une séance de ce type, adaptée à la phase
NUANCE = {"côtes": {"foncier": _q(hills_short), "développement": _q(hills_medium),
                    "spécifique": _q(hills_long)},
          "vitesse": {"foncier": _q(fartlek), "développement": _q(vma), "spécifique": _q(vma, 2)}}
SECOND = [_q(vma), _q(seuil, 2)]
LIGHT = [_q(hill_sprints), _q(fartlek)]
LONG = {("foncier", False): ["classique"], ("développement", False): ["classique", "progressive"],
        ("spécifique", False): ["progressive", "classique"],
        ("foncier", True): ["vallonnée"], ("développement", True): ["vallonnée", "descentes"],
        ("spécifique", True): ["spécifique", "vallonnée", "descentes"],
        ("maintien", False): ["classique", "progressive"], ("maintien", True): ["vallonnée", "descentes"],
        ("reprise", False): ["classique"], ("reprise", True): ["vallonnée"],
        ("vitesse", False): ["classique"], ("route longue", False): ["progressive", "classique"],
        ("trail", True): ["vallonnée", "descentes", "spécifique"]}


def rotate(options: list, week_in_phase: int, shift: int = 0):
    """Variante de la semaine et palier : la variante change chaque semaine, le palier monte à
    chaque tour complet des variantes."""
    i = week_in_phase + shift
    return options[i % len(options)], i // len(options)


def quality(phase: str, kind: str, rank: int, trail: bool, week_in_phase: int, p: dict,
            day_max: float, nuance: str | None = None) -> dict:
    """Séance de qualité du créneau `rank` (0 : la séance clé), tournante, ramenée au temps du jour ;
    nuance du coureur une semaine de charge sur deux."""
    if kind in ("affûtage", "course"):
        s = reminder(trail, p)
        return with_gain(s if s["minutes"] <= day_max else reminder(trail, p, compact=True), p)
    if kind == "allégée":
        make, level = rotate(LIGHT, week_in_phase)
    elif rank == 0 and nuance in NUANCE and phase in NUANCE[nuance] and week_in_phase % 2 == 1:
        make, level = NUANCE[nuance][phase], week_in_phase // 4
    elif rank == 0:
        make, level = rotate(QUALITY[(phase, trail)], week_in_phase)
    else:
        make, level = rotate(SECOND, week_in_phase)
    return with_gain(fit(lambda lv, compact=False: make(lv, p, compact), level, day_max), p)


def test_run(trail: bool, p: dict) -> dict:
    """Test facultatif du maintien de forme : un repère sans dossard, de temps en temps. Route : 5 km
    à fond, réguliers ; trail : une montée connue chronométrée à l'effort. Le résultat entre dans
    les meilleurs efforts (courbe allure-durée, VAM) sans rien saisir."""
    lthr = p.get("lthr")
    if trail:
        work = step("work", "une montée connue de 15 à 25 min, chronométrée, à l'effort le plus "
                            "haut que tu peux tenir jusqu'en haut", 20, target(VO2, lthr))
        label, note = "Test en montée", "Toujours la même montée, pour comparer d'une fois sur l'autre."
    else:
        work = step("work", "5 km à fond, réguliers du début à la fin", 25, target(VO2, lthr))
        label, note = "Test sur 5 km", "Sur un parcours plat et connu, pour comparer d'une fois sur l'autre."
    s = _session("test", label, [_warmup(WARMUP_MIN, lthr), work, _cooldown(COOLDOWN_MIN, lthr)],
                 "Facultatif : un repère de forme sans dossard. " + note
                 + " Sans envie de test, fais la séance de qualité habituelle à la place.")
    return with_gain(s, p)


def long_variant(phase: str, kind: str, trail: bool, week_in_phase: int) -> str:
    if kind in ("affûtage", "course", "allégée"):
        return "vallonnée" if trail else "classique"
    variant, _ = rotate(LONG[(phase, trail)], week_in_phase)
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
                main: dict) -> dict | None:
    """Seconde proposition pour une séance de qualité, au même rôle : la variante suivante du
    catalogue de la semaine, sur l'autre terrain si possible (côtes contre plat), sinon simplement
    d'un autre type. Aucune en semaine d'affûtage ou de course (le rappel est la séance)."""
    if kind in ("affûtage", "course"):
        return None
    if kind == "allégée":
        options = LIGHT
    elif rank == 0:
        options = QUALITY[(phase, trail)]
    else:
        options = SECOND
    hilly = main["type"] in HILLY
    candidates = []
    for shift in range(1, len(options)):
        make, level = rotate(options, week_in_phase, shift)
        s = with_gain(fit(lambda lv, compact=False, m=make: m(lv, p, compact), level, day_max), p)
        if s["type"] != main["type"]:
            candidates.append(s)
    if not candidates:
        return None
    other = [s for s in candidates if (s["type"] in HILLY) != hilly]
    return (other or candidates)[0]


def long_alternative(phase: str, kind: str, trail: bool, week_in_phase: int, variant: str, minutes: float,
                     p: dict, km: bool) -> dict | None:
    """Seconde proposition pour la sortie longue : une autre variante de la phase (ou, à défaut,
    progressive sur route, avec descentes en trail), même durée, en endurance."""
    phase_key = (phase, trail) if (phase, trail) in LONG else None
    options = list(LONG[phase_key]) if phase_key else []
    options += ["vallonnée", "descentes"] if trail else ["progressive", "classique"]
    other = next((v for v in options if v != variant), None)
    return long_run(other, minutes, p, km) if other else None


def easy_alternative(s: dict, p: dict) -> dict:
    """Seconde proposition pour un footing : vallonné au lieu du plat, ou l'inverse, même durée."""
    hilly = s["type"] == "footing vallonné"
    return easy_run(s["minutes"], p, not hilly, km=hilly)


# ---------- bibliothèque de séances (étape 9) ----------

def library(p: dict) -> list[dict]:
    """Toutes les séances du coach par famille, au premier palier et au plus haut, avec les allures
    et la FC du coureur : pour choisir, remplacer ou simplement s'inspirer."""
    def both(make):
        first, last = make(0, p), make(9, p)
        same = last["label"] == first["label"] and last["minutes"] == first["minutes"]
        return [first] if same else [first, last]
    return [
        {"family": "Endurance", "why": "La base : 80 % du temps, en aisance respiratoire.",
         "sessions": [easy_run(45, p, False), easy_run(50, p, True), steady_run(50, p), strides(40, p)]},
        {"family": "Sorties longues",
         "why": "L'endurance pour durer ; une fin rapide apprend à accélérer fatigué.",
         "sessions": [long_run("classique", 90, p), long_run("progressive", 90, p),
                      long_run("classique", 90, p, steady_finish=True),
                      long_run("vallonnée", 100, p, km=False),
                      long_run("descentes", 100, p, km=False), long_run("spécifique", 110, p, km=False)]},
        {"family": "Fartlek et pyramide", "why": "Des changements d'allure au feeling, pour varier.",
         "sessions": both(fartlek) + both(pyramid)},
        {"family": "Seuil et tempo",
         "why": "L'allure qu'on tiendrait une heure : le moteur des courses longues.",
         "sessions": both(seuil) + both(tempo)},
        {"family": "VMA", "why": "Courtes et vives : la vitesse maximale aérobie, pour le 10 km et moins.",
         "sessions": both(vma)},
        {"family": "Côtes", "why": "Force et puissance, et le terrain des trails.",
         "sessions": [with_gain(s, p) for s in both(hill_sprints) + both(hills_short) + both(hills_medium)
                      + both(hills_long)]},
        {"family": "Trail", "why": "Monter longtemps, marcher vite, descendre sans se faire mal.",
         "sessions": [with_gain(s, p) for s in both(uphill_tempo) + both(power_hike) + both(downhill)]},
        {"family": "Allure course et tests", "why": "Les sensations du jour J, et un repère de forme.",
         "sessions": both(race_pace) + [test_run(False, p), test_run(True, p)]},
    ]
