"""
Coach (phase 4), étape 4 : bilan du dimanche et réajustement de la semaine suivante (fonctions
pures, versionnées, plus le stockage des réponses et des bilans figés).

Bilan d'une semaine, sans jugement : une semaine peu suivie est un fait, le plan suivant en tient
compte.
- Verdict (choix de Greg) : le plus bas de la part des séances prévues faites et de la part de la
  charge prévue réalisée ; bien suivie dès 80 %, partiellement dès 50 %, peu en dessous.
- Séances faites face aux prévues, séance clé, séances non faites (jamais rattrapées), charge,
  fitness réelle face à celle que prévoyait le plan, temps prévus des échéances au début et à la
  fin de la semaine.

Réajustement de la semaine suivante, à partir des deux réponses du coureur (semaine chargée,
normale ou libre ; frais, normal ou fatigué) et de la forme réelle :
- semaine chargée : un tiers des séances en moins, la séance clé et la sortie longue gardées
  (choix de Greg, coach_plan.drop_for_busy_week) ;
- semaine libre : les jours optionnels entrent dans le plan, sans charge en plus ;
- fatigue ressentie ou forme trop basse (zone de surcharge de la page Forme, rapportée à la
  fitness) : semaine allégée à la place d'une semaine de charge, la progression est décalée ;
- en avance sur le plan (fitness au-dessus de celle prévue) : progression maintenue sans accélérer,
  la charge de la semaine suivante ne dépasse pas celle que prévoyait le plan du lundi ;
- séances manquées : jamais rattrapées, le plan repart de la forme réelle (c'est déjà le cas, il
  est recalculé chaque semaine).
"""
import json
from datetime import date, datetime, timedelta

from . import stats

REVIEW_VERSION = 1
GOOD_SHARE = 0.8                # bien suivie : au moins 80 % des séances et de la charge
PARTIAL_SHARE = 0.5             # partiellement suivie : au moins 50 %
NEXT_WEEK = {"chargée": "Chargée", "normale": "Normale", "libre": "Libre"}
FEELINGS = {"frais": "Frais", "normal": "Normal", "fatigué": "Fatigué"}
LOW_FORM_ZONE = "overload"      # forme trop basse : zone de surcharge (sous −30 % de la fitness)
FITNESS_SAME = 0.5              # fitness « comme prévu » : à moins d'un demi-point (arrondi affiché)
VERDICTS = {"good": "Semaine bien suivie", "partial": "Semaine partiellement suivie",
            "low": "Semaine peu suivie", "none": "Semaine sans séance prévue"}


def _pct(done: float, planned: float) -> int | None:
    return round(done / planned * 100) if planned else None


def verdict(planned: dict, done: dict) -> dict:
    """Verdict de la semaine : le plus bas de la part des séances faites et de la part de la charge
    réalisée (chacune plafonnée à 100 %)."""
    sessions = _pct(done["sessions"], planned["sessions"])
    load = _pct(done["load"], planned["load"])
    shares = [min(x, 100) for x in (sessions, load) if x is not None]
    if not shares:
        key = "none"
    else:
        share = min(shares) / 100
        key = "good" if share >= GOOD_SHARE else "partial" if share >= PARTIAL_SHARE else "low"
    return {"key": key, "label": VERDICTS[key], "sessions_pct": sessions, "load_pct": load,
            "share_pct": min(shares) if shares else None}


def form_state(fitness: float, fatigue: float) -> dict:
    """Forme (fitness − fatigue) en % de la fitness et sa zone (mêmes seuils que la page Forme,
    rapportés à la fitness pour valoir quel que soit le volume du coureur)."""
    form = fitness - fatigue
    pct = form / fitness * 100 if fitness > 0 else 0.0
    key, label = stats.form_zone(pct)
    return {"fitness": round(fitness, 1), "form": round(form, 1), "pct": round(pct),
            "zone": key, "label": label, "low": fitness > 0 and key == LOW_FORM_ZONE}


def _num(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def review(week: dict, plan: dict, end: dict, races: list[dict]) -> dict:
    """Bilan d'une semaine. week : écran « Cette semaine » (coach_week.week_view) de la semaine ;
    plan : plan calculé son lundi (fitness prévue en fin de semaine, charge et type prévus la
    semaine suivante) ; end : fitness et fatigue réelles le dimanche soir ; races : échéances à venir
    avec leur temps prévu au début (before_s) et à la fin (after_s) de la semaine."""
    planned, done = week["planned"], week["done"]
    v = verdict(planned, done)
    rows = [s for s in week["sessions"] if not s.get("optional") and not s.get("main")]
    missed = [s for s in rows if s["status"] == "passée"]
    moved = [s for s in rows if s.get("done") and s["done"]["date"] != s["date"]]
    key = week.get("key")
    w0 = plan["weeks"][0]
    nxt = plan["weeks"][1] if len(plan["weeks"]) > 1 else None
    form = form_state(end["fitness"], end["fatigue"])
    planned_fit = w0.get("fitness_end")
    ahead = planned_fit is not None and form["fitness"] > planned_fit
    lines = []
    if not planned["sessions"]:
        runs = f" ; {_plural(done['runs'], 'sortie')}, charge {done['load']}" if done["runs"] else ""
        lines.append(f"Aucune séance n'était prévue cette semaine{runs}.")
    else:
        n, p = done["sessions"], planned["sessions"]
        extra = f", {_plural(len(week['extra']), 'sortie')} en plus" if week["extra"] else ""
        lines.append(f"{_plural(n, 'séance')} faite{'s' if n > 1 else ''} sur {p} "
                     f"prévue{'s' if p > 1 else ''}{extra} ; "
                     f"charge {done['load']} pour {planned['load']} prévue.")
    if key:
        if key.get("type") == "course":
            status = {"faite": "courue", "passée": "pas courue"}.get(key["status"], "encore à courir")
            lines.append(f"{key['label']} : {status}.")
        else:
            status = {"faite": "faite", "passée": "pas faite cette fois"}.get(key["status"], "encore à faire")
            lines.append(f"Séance clé, {key['label']} : {status}.")
    pending = [s for s in rows if s["status"] in ("aujourd'hui", "à venir")]
    if pending:
        lines.append(f"Bilan provisoire : {_plural(len(pending), 'séance')} encore à faire ou pas "
                     "encore synchronisée" + ("s." if len(pending) > 1 else "."))
    if missed:
        lines.append(f"{_plural(len(missed), 'séance')} non faite{'s' if len(missed) > 1 else ''} : "
                     "pas de rattrapage, la suite du plan part de ta forme réelle.")
    if moved:
        lines.append(f"{_plural(len(moved), 'séance')} faite{'s' if len(moved) > 1 else ''} un autre "
                     "jour que prévu.")
    if planned_fit is not None and (planned_fit or form["fitness"]):
        delta = form["fitness"] - planned_fit
        if abs(delta) < FITNESS_SAME:
            lines.append(f"Fitness {_num(form['fitness'])}, comme prévu par le plan.")
        else:
            lines.append(f"Fitness {_num(form['fitness'])} pour {_num(planned_fit)} prévue : "
                         + ("en avance sur le plan." if delta > 0
                            else "un peu en retrait, le plan repart de là."))
    out_races = []
    for r in races:
        before, after = r.get("before_s"), r.get("after_s")
        out_races.append({"name": r["name"], "priority": r["priority"], "race_date": r["race_date"],
                          "before_s": before, "after_s": after, "target_s": r.get("target_s"),
                          "delta_s": round(after - before) if before and after else None})
    return {"version": REVIEW_VERSION, "monday": week["monday"], "verdict": v,
            "planned": planned, "done": done, "lines": lines,
            "key": {"label": key["label"], "status": key["status"], "type": key.get("type")} if key else None,
            "missed": [{"label": s["label"], "day": s["day"]} for s in missed],
            "pending": len(pending),
            "fitness": {"planned": planned_fit, "actual": form["fitness"], "ahead": ahead},
            "form": form, "races": out_races,
            "next": {"monday": nxt["monday"], "kind": nxt["kind"], "phase": nxt["phase"],
                     "load": nxt["planned_load"]} if nxt else None}


def adjustment(answers: dict | None, summary: dict | None) -> dict | None:
    """Réajustement de la semaine qui suit une semaine passée en revue : réponses du coureur
    (semaine chargée, normale ou libre ; ressenti) et bilan (forme réelle, avance sur le plan).
    None quand rien ne change."""
    answers = answers or {}
    nxt = (summary or {}).get("next")
    if not nxt:
        return None
    light = None
    form = (summary or {}).get("form") or {}
    if answers.get("feeling") == "fatigué":
        light = "Tu te sens fatigué : semaine allégée (−30 %), la progression reprend ensuite."
    elif form.get("low"):
        light = (f"Forme très basse ({form['pct']} % de la fitness, zone de surcharge) : semaine "
                 "allégée (−30 %), la progression reprend ensuite.")
    ahead = ((summary or {}).get("fitness") or {}).get("ahead")
    adj = {"monday": nxt["monday"], "light": light, "busy": answers.get("next_week") == "chargée",
           "free": answers.get("next_week") == "libre",
           "cap_load": nxt["load"] if ahead and nxt.get("load") else None}
    return adj if any(adj[k] for k in ("light", "busy", "free", "cap_load")) else None


def orientation(answers: dict | None, summary: dict) -> list[str]:
    """Ce que le coach fera de la semaine suivante, en une ou deux phrases."""
    adj = adjustment(answers, summary)
    nxt = summary.get("next")
    if not nxt:
        return ["Plus de semaine prévue après celle-ci dans le plan."]
    if not adj:
        return ["Semaine suivante telle que prévue par le plan."]
    out = []
    if adj["light"]:
        out.append(adj["light"])
    if adj["busy"]:
        out.append("Semaine chargée : environ un tiers des séances en moins, la séance clé et la "
                   "sortie longue gardées.")
    if adj["free"]:
        out.append("Semaine libre : tes jours optionnels entrent dans le plan, sans hausse de la "
                   "progression.")
    if adj["cap_load"]:
        out.append("En avance sur le plan : progression maintenue, sans accélérer.")
    return out


def clean_answers(values) -> dict:
    """Réponses du bilan : semaine suivante et ressenti, chacune facultative (None l'efface)."""
    if not isinstance(values, dict):
        raise ValueError("Réponses invalides.")
    out = {}
    for key, allowed in (("next_week", NEXT_WEEK), ("feeling", FEELINGS)):
        value = values.get(key)
        if value is not None and value not in allowed:
            raise ValueError(f"{key} doit valoir {', '.join(allowed)} ou null.")
        out[key] = value
    return out


# ---------- stockage ----------

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def all_reviews(conn) -> dict[str, dict]:
    out = {}
    for r in conn.execute("SELECT * FROM coach_reviews"):
        row = dict(r)
        row["summary"] = json.loads(row["summary"]) if row["summary"] else None
        out[row["monday"]] = row
    return out


def save_answers(conn, monday_: date, answers: dict):
    with conn:
        conn.execute(
            "INSERT INTO coach_reviews (monday, next_week, feeling, answered_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(monday) DO UPDATE SET next_week=excluded.next_week, "
            "feeling=excluded.feeling, answered_at=excluded.answered_at",
            (monday_.isoformat(), answers.get("next_week"), answers.get("feeling"), _now()))


def save_summary(conn, monday_: date, summary: dict):
    with conn:
        conn.execute(
            "INSERT INTO coach_reviews (monday, summary, summarized_at) VALUES (?, ?, ?) "
            "ON CONFLICT(monday) DO UPDATE SET summary=excluded.summary, "
            "summarized_at=excluded.summarized_at",
            (monday_.isoformat(), json.dumps(summary, ensure_ascii=False), _now()))


def sunday(monday_: date) -> date:
    return monday_ + timedelta(days=6)
