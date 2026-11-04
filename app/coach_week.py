"""
Coach (phase 4), étape 3 : écran « Cette semaine » (fonctions pures, versionnées).

- La semaine prévue est celle du plan calculé le lundi : elle ne bouge pas au fil des sorties de
  la semaine (seuls un changement de réglages ou de calendrier la recalculent).
- Séances faites détectées dans les sorties synchronisées, sans rien saisir : chaque sortie est
  rapprochée de la séance prévue la plus proche, le même jour d'abord, sinon à 2 jours au plus
  (séance déplacée) ; une sortie sans séance proche compte « en plus ».
- Rôle d'une sortie lu sur son temps par zone de FC (mêmes seuils que le plan) : facile, soutenue
  ou séance dure ; sortie longue si elle dure au moins 80 % de la sortie longue prévue.
- Une séance non faite n'est jamais rattrapée : elle est simplement passée.
- Séance clé : celle que le plan marque (qualité principale, sinon sortie longue, sinon course) ;
  ce qui peut sauter si le temps manque : séances optionnelles, puis footings, du plus court au
  plus long, jamais la séance clé, la sortie longue ni une course.
"""
import math
from datetime import date, timedelta

from .coach_plan import WEEKDAYS, _run_kind

WEEK_VERSION = 1
MOVE_MAX_DAYS = 2           # séance déplacée : faite au plus 2 jours avant ou après
DAY_COST = 1.5              # rapprochement : un jour d'écart pèse plus qu'un rôle différent
ROLE_COST = 1.0
LONG_SHARE_DONE = 0.8       # sortie longue faite : au moins 80 % de la durée prévue
SHORT_SHARE = 0.8           # « plus courte » sous 80 % de la durée prévue, « plus longue » au-delà de 125 %
LONG_SHARE = 1.25
SKIP_MAX = 2                # au plus 2 séances proposées à sauter
SKIPPABLE = ("footing", "footing vallonné", "footing soutenu", "lignes droites")
ROLE_LABELS = {"easy": "facile", "steady": "soutenue", "hard": "séance dure", "long": "sortie longue",
               "race": "course"}


def planned_role(s: dict) -> str:
    """Rôle d'une séance prévue : course, sortie longue, séance dure ou facile."""
    if s["type"] == "course":
        return "race"
    if s["type"] == "sortie longue":
        return "long"
    return "hard" if s.get("hard") else "easy"


def done_role(a: dict, long_min: float | None, race_ids=()) -> str:
    """Rôle d'une sortie faite : course confirmée, sortie longue (au moins 80 % de la sortie
    longue prévue, en endurance), séance dure, soutenue ou facile (temps par zone de FC ; facile
    sans FC)."""
    if a.get("id") in race_ids:
        return "race"
    kind = _run_kind(a) or "easy"
    minutes = (a.get("moving_duration_s") or 0) / 60
    if long_min and kind != "hard" and minutes >= LONG_SHARE_DONE * long_min:
        return "long"
    return kind


def _compatible(planned: str, done: str) -> bool:
    if planned == done:
        return True
    # une course faite à la place d'une séance dure, une sortie soutenue à la place d'un footing
    return (planned, done) in {("hard", "race"), ("race", "hard"), ("easy", "steady")}


def _cost(s: dict, a: dict, role: str) -> float | None:
    days = abs((a["start"].date() - date.fromisoformat(s["date"])).days)
    if days > MOVE_MAX_DAYS:
        return None
    planned, minutes = s["role"], (a.get("moving_duration_s") or 0) / 60
    ratio = abs(math.log(max(minutes, 1) / max(s.get("minutes") or minutes or 1, 1)))
    return days * DAY_COST + (0 if _compatible(planned, role) else ROLE_COST) + ratio


def _note(s: dict, a: dict, role: str) -> str | None:
    """Écart entre la séance prévue et la sortie faite, en quelques mots, sans jugement."""
    notes = []
    days = (a["start"].date() - date.fromisoformat(s["date"])).days
    if days:
        notes.append(f"faite {abs(days)} jour{'s' if abs(days) > 1 else ''} "
                     f"{'plus tard' if days > 0 else 'plus tôt'}")
    minutes = round((a.get("moving_duration_s") or 0) / 60)
    if s.get("minutes"):
        if minutes < SHORT_SHARE * s["minutes"]:
            notes.append(f"plus courte ({minutes} min au lieu de {s['minutes']})")
        elif minutes > LONG_SHARE * s["minutes"]:
            notes.append(f"plus longue ({minutes} min au lieu de {s['minutes']})")
    if s["role"] in ("easy", "long") and role in ("steady", "hard"):
        notes.append("plus soutenue que prévu")
    elif s["role"] in ("hard", "race") and role in ("easy", "long"):
        notes.append("plus facile que prévu")
    return ", ".join(notes) or None


def _done(a: dict, role: str) -> dict:
    return {"id": a.get("id"), "name": a.get("name"), "date": a["start"].date().isoformat(),
            "minutes": round((a.get("moving_duration_s") or 0) / 60),
            "distance_km": round(a.get("distance_km") or 0, 1), "gain_m": round(a.get("gain_m") or 0),
            "load": round(a.get("hrss") or 0), "role": role, "role_label": ROLE_LABELS[role]}


def match(sessions: list[dict], acts, monday_: date, today: date, race_ids=()) -> dict:
    """Séances prévues de la semaine face aux sorties faites (de lundi à aujourd'hui inclus).
    Rapprochement glouton, du couple le plus proche au plus éloigné (jour, rôle, durée) ; chaque
    sortie va à une séance au plus. Statut de chaque séance : faite, à venir, aujourd'hui, passée
    (non faite, jamais rattrapée) ; sorties sans séance : en plus."""
    end = monday_ + timedelta(days=6)
    week_acts = [a for a in acts if monday_ <= a["start"].date() <= min(end, today)]
    rows = [{**s, "role": planned_role(s)} for s in sessions]
    long_min = max((s["minutes"] or 0 for s in rows if s["role"] == "long"), default=None)
    roles = [done_role(a, long_min, race_ids) for a in week_acts]
    pairs = []
    for i, s in enumerate(rows):
        for j, a in enumerate(week_acts):
            cost = _cost(s, a, roles[j])
            if cost is not None:
                pairs.append((cost, i, j))
    used_s, used_a = {}, set()
    for _, i, j in sorted(pairs):
        if i not in used_s and j not in used_a:
            used_s[i] = j
            used_a.add(j)
    for i, s in enumerate(rows):
        if i in used_s:
            a, role = week_acts[used_s[i]], roles[used_s[i]]
            s["done"] = _done(a, role)
            s["note"] = _note(s, a, role)
            s["status"] = "faite"
        elif s["date"] > today.isoformat():
            s["status"] = "à venir"
        elif s["date"] == today.isoformat():
            s["status"] = "aujourd'hui"
        else:
            s["status"] = "passée"
    extra = [_done(a, roles[j]) for j, a in enumerate(week_acts) if j not in used_a]
    return {"sessions": rows, "extra": extra}


def skippable(rows: list[dict], today: date) -> list[dict]:
    """Ce qui peut sauter si le temps manque, parmi les séances encore à faire : les optionnelles,
    puis les footings, du plus court au plus long ; jamais la séance clé, la sortie longue ni une
    course."""
    left = [s for s in rows if s["status"] in ("à venir", "aujourd'hui") and not s.get("key")
            and (s.get("optional") or s["type"] in SKIPPABLE)]
    left.sort(key=lambda s: (not s.get("optional"), s.get("habit") is not None, s.get("minutes") or 0))
    return left[:SKIP_MAX]


def key_reason(s: dict, phase: str) -> str:
    """Pourquoi la séance clé compte, en une phrase."""
    if s["type"] == "course":
        return "La course de la semaine : le reste s'organise autour, pour y arriver frais."
    if s["type"] == "sortie longue":
        return "La sortie qui construit l'endurance pour la durée de la course."
    if phase == "spécifique":
        return ("La séance la plus proche de l'effort de la course : celle à garder si la semaine "
                "se complique.")
    if phase == "affûtage":
        return "Elle garde l'intensité pendant que le volume baisse : courte, mais à faire."
    return f"La séance qui fait progresser en phase de {phase} : celle à garder si la semaine se complique."


def week_view(plan_week: dict, acts, today: date, race_ids=()) -> dict:
    """Écran « Cette semaine » : séances prévues et faites, séance clé et pourquoi, ce qui peut
    sauter, bilan de la semaine en cours (séances, minutes, charge, D+ faits face aux prévus)."""
    monday_ = date.fromisoformat(plan_week["monday"])
    m = match(plan_week["sessions"], acts, monday_, today, race_ids)
    rows = m["sessions"]
    counted = [s for s in rows if not s.get("optional") and not s.get("main")]
    done = [s["done"] for s in rows if s.get("done")] + m["extra"]
    key = next((s for s in rows if s.get("key")), None)
    days = []
    for k in range(7):
        d = (monday_ + timedelta(days=k)).isoformat()
        days.append({"weekday": k, "date": d, "day": WEEKDAYS[k], "is_today": d == today.isoformat(),
                     "sessions": [s for s in rows if s["date"] == d],
                     "extra": [x for x in m["extra"] if x["date"] == d]})
    return {
        "days": days,
        "version": WEEK_VERSION, "monday": plan_week["monday"], "phase": plan_week["phase"],
        "kind": plan_week["kind"], "sessions": rows, "extra": m["extra"],
        "today_session": next((s for s in rows if s["date"] == today.isoformat()), None),
        "key": key, "key_reason": key_reason(key, plan_week["phase"]) if key else None,
        "skip": skippable(rows, today),
        "planned": {"sessions": len(counted), "minutes": plan_week["minutes"],
                    "load": plan_week["planned_load"], "gain_m": plan_week.get("gain_m") or 0},
        "done": {"sessions": sum(1 for s in counted if s.get("done")),
                 "runs": len(done), "minutes": sum(d["minutes"] for d in done),
                 "load": sum(d["load"] for d in done), "gain_m": sum(d["gain_m"] for d in done)},
        "periods": plan_week.get("periods") or [], "events": plan_week.get("events") or [],
        "strength": plan_week.get("strength") or 0,
    }
