"""
Coach (phase 4), étape 1 : calendrier des échéances et démarrage (fonctions pures, plus le
stockage du calendrier).

Calendrier séparé des courses suivies de l'estimateur (choix de Greg) : chaque échéance a une
date et une priorité A (objectif principal, plan périodisé pour elle), B (course importante,
mini-affûtage) ou C (préparation, semaine allégée).

Disponibilités et habitudes, facultatives, déduites de l'historique quand elles ne sont pas
saisies : règles de majorité générales, aucune constante calée sur un coureur.
- jour possible : une sortie ce jour-là au moins une semaine sur deux (HISTORY_WEEKS dernières
  semaines) ; optionnel : au moins une semaine sur quatre ; durée habituelle : médiane du temps en
  mouvement des sorties de ce jour ;
- habitude : lieu de passage d'un jour possible (case de PLACE_CELL_M de côté) traversé par au
  moins la moitié des sorties de ce jour sur les HABIT_WEEKS dernières semaines, le plus éloigné du
  départ (hors de ses abords) : le but de la sortie, quel que soit le chemin pris pour y aller.
"""
import math
from datetime import date, datetime, timedelta
from statistics import median

import numpy as np

from . import tracked

COACH_VERSION = 1
HISTORY_WEEKS = 12
HABIT_WEEKS = 26             # habitudes : une demi-année, pour voir revenir un lieu
HABIT_SHARE = 0.5            # majorité : une semaine sur deux, une sortie sur deux
OPTIONAL_SHARE = 0.25        # optionnel : une semaine sur quatre
PLACE_CELL_M = 200.0         # case d'un lieu de passage, de l'ordre de la précision des tracés résumés
PLACE_START_M = 2 * PLACE_CELL_M   # abords du départ, exclus (on y passe à chaque sortie)
STATUSES = ("oui", "optionnel", "non")
PRIORITIES = {"A": "Objectif principal", "B": "Course importante", "C": "Préparation"}
WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
MAX_DAY_MIN = 600


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------- calendrier ----------

def clean(cfg, values: dict) -> dict:
    """Champs d'une échéance, vérifiés (mêmes règles que les courses suivies, plus une date et une
    priorité obligatoires) ; ValueError si la saisie est invalide."""
    race = tracked.clean(cfg, values)
    if not race["race_date"]:
        raise ValueError("Donne la date de la course.")
    priority = str(values.get("priority") or "").upper()
    if priority not in PRIORITIES:
        raise ValueError("Choisis une priorité A, B ou C.")
    return {**race, "priority": priority}


def create(conn, race: dict) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO coach_races (name, race_date, priority, gpx_id, distance_m, gain_m, target_s,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (race["name"], race["race_date"], race["priority"], race["gpx_id"], race["distance_m"],
             race["gain_m"], race["target_s"], _now()))
    return cur.lastrowid


def update(conn, race_id: int, race: dict):
    with conn:
        conn.execute(
            "UPDATE coach_races SET name=?, race_date=?, priority=?, gpx_id=?, distance_m=?, gain_m=?,"
            " target_s=? WHERE id=?",
            (race["name"], race["race_date"], race["priority"], race["gpx_id"], race["distance_m"],
             race["gain_m"], race["target_s"], race_id))


def set_target(conn, race_id: int, target_s: float | None):
    with conn:
        conn.execute("UPDATE coach_races SET target_s=? WHERE id=?", (target_s, race_id))


def delete(conn, race_id: int):
    with conn:
        conn.execute("DELETE FROM coach_races WHERE id=?", (race_id,))


def get(conn, race_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM coach_races WHERE id=?", (race_id,)).fetchone()
    return dict(row) if row else None


def all_races(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM coach_races ORDER BY race_date, priority")]


def calendar(races: list[dict], today: date) -> dict:
    """Échéances à venir (dans l'ordre des dates, compte à rebours) et passées."""
    upcoming, past = [], []
    for r in races:
        d = date.fromisoformat(r["race_date"])
        row = {**r, "days_left": (d - today).days, "weeks_left": (d - today).days // 7,
               "priority_label": PRIORITIES[r["priority"]]}
        (upcoming if d >= today else past).append(row)
    past.sort(key=lambda r: r["race_date"], reverse=True)
    main = next((r for r in upcoming if r["priority"] == "A"), None)
    return {"upcoming": upcoming, "past": past, "main": main}


# ---------- disponibilités et habitudes ----------

def _recent(acts, today: date, weeks: int) -> tuple[list[dict], date]:
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks)   # lundi, semaines pleines
    end = today - timedelta(days=today.weekday())                              # semaine en cours exclue
    return [a for a in acts if start <= a["start"].date() < end], start


def availability_from_history(acts, today: date, weeks: int = HISTORY_WEEKS) -> dict:
    """Pour chaque jour de la semaine : part des semaines avec une sortie ce jour-là, durée
    habituelle (médiane du temps en mouvement), statut oui, optionnel ou non ; séances par
    semaine (médiane des semaines pleines)."""
    recent, start = _recent(acts, today, weeks)
    days = []
    for wd in range(7):
        runs = [a for a in recent if a["start"].weekday() == wd]
        week_set = {(a["start"].date() - start).days // 7 for a in runs}
        durations = [a["moving_duration_s"] for a in runs if a.get("moving_duration_s")]
        share = len(week_set) / weeks
        status = "oui" if share >= HABIT_SHARE else "optionnel" if share >= OPTIONAL_SHARE else "non"
        days.append({"weekday": wd, "label": WEEKDAYS[wd], "weeks": len(week_set), "share": round(share, 2),
                     "habitual": status == "oui", "status": status,
                     "usual_min": round(median(durations) / 60) if durations else None})
    per_week = [sum(1 for a in recent if (a["start"].date() - start).days // 7 == w) for w in range(weeks)]
    return {"weeks": weeks, "days": days, "sessions_per_week": median(per_week) if recent else 0}


def _cells(track, lat0: float) -> set[tuple[int, int]]:
    """Cases traversées par un tracé (lat, lon), densifié pour n'en sauter aucune."""
    kx = 111320 * math.cos(math.radians(lat0))
    xs, ys = track[:, 1] * kx, track[:, 0] * 111320
    cells = {(int(ys[0] // PLACE_CELL_M), int(xs[0] // PLACE_CELL_M))}
    for i in range(len(xs) - 1):
        n = max(1, math.ceil(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) / (PLACE_CELL_M / 2)))
        for t in np.linspace(0, 1, n + 1)[1:]:
            cells.add((int((ys[i] + t * (ys[i + 1] - ys[i])) // PLACE_CELL_M),
                       int((xs[i] + t * (xs[i + 1] - xs[i])) // PLACE_CELL_M)))
    return cells


def _distance_m(a, b) -> float:
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])))


def habits_from_history(acts, tracks: dict, today: date, weeks: int = HABIT_WEEKS,
                        days_weeks: int = HISTORY_WEEKS) -> list[dict]:
    """Lieu de passage habituel de chaque jour possible : la case traversée par au moins la moitié
    des sorties de ce jour, la plus éloignée du départ. tracks : tracé résumé (lat, lon) de chaque
    sortie (activity_tracks)."""
    recent, _ = _recent(acts, today, weeks)
    days = availability_from_history(acts, today, days_weeks)["days"]
    out = []
    for wd in (d["weekday"] for d in days if d["habitual"]):
        runs = [a for a in recent if a["start"].weekday() == wd and a["id"] in tracks]
        if len(runs) < 2:
            continue
        start = tuple(float(v) for v in np.median(np.array([tracks[a["id"]][0] for a in runs]), axis=0))
        passing = {}
        for a in runs:
            for c in _cells(tracks[a["id"]], start[0]):
                passing.setdefault(c, []).append(a)
        kx = 111320 * math.cos(math.radians(start[0]))
        best, best_d = None, PLACE_START_M
        for c, rows in passing.items():
            if len(rows) / len(runs) < HABIT_SHARE:
                continue
            centre = ((c[0] + 0.5) * PLACE_CELL_M / 111320, (c[1] + 0.5) * PLACE_CELL_M / kx)
            d = _distance_m(centre, start)
            if d > best_d:
                best, best_d = (c, centre), d
        if best is None:
            continue
        rows = passing[best[0]]
        last = max(rows, key=lambda a: a["start"])
        out.append({"weekday": wd, "label": WEEKDAYS[wd],
                    "place": [round(best[1][0], 5), round(best[1][1], 5)],
                    "from_start_m": round(best_d, -1), "name": last.get("name"), "activity_id": last["id"],
                    "count": len(rows), "runs": len(runs), "weeks": weeks,
                    "distance_km": round(median(a["distance_km"] for a in rows), 1),
                    "gain_m": round(median(a["gain_m"] for a in rows)),
                    "moving_min": round(median(a["moving_duration_s"] or 0 for a in rows) / 60)})
    return out


def _status(saved: dict) -> str:
    """Statut d'un jour saisi ; les premières saisies n'avaient qu'une case possible / pas possible."""
    return saved.get("status") or ("oui" if saved.get("available") else "non")


def effective_availability(stored: list | None, inferred: dict) -> list[dict]:
    """Disponibilités par jour : saisies par Greg si elles existent, sinon déduites de l'historique
    (statut, durée habituelle)."""
    by_day = {d["weekday"]: d for d in (stored or [])}
    out = []
    for d in inferred["days"]:
        s = by_day.get(d["weekday"])
        out.append({**d, "source": "saisie" if s else "historique",
                    "status": _status(s) if s else d["status"],
                    "max_min": s["max_min"] if s else (d["usual_min"] if d["status"] != "non" else None)})
    return out


def clean_profile(values: dict) -> dict:
    """Disponibilités saisies (7 jours : oui, optionnel ou non, durée maximale) et habitudes
    (lieu, nom, gardée ou non), seulement les champs envoyés (null : retour à l'historique) ;
    ValueError si invalide."""
    if not isinstance(values, dict) or not set(values) & {"availability", "habits"}:
        raise ValueError("Saisie invalide.")
    out = {}
    availability = values.get("availability")
    if availability is not None:
        if not isinstance(availability, list) or {d.get("weekday") for d in availability} != set(range(7)):
            raise ValueError("Disponibilités attendues pour les 7 jours.")
        cleaned = []
        for d in sorted(availability, key=lambda d: d["weekday"]):
            if d.get("status") not in STATUSES:
                raise ValueError("Chaque jour : oui, optionnel ou non.")
            minutes = d.get("max_min")
            if minutes in (None, ""):
                minutes = None
            elif (isinstance(minutes, bool) or not isinstance(minutes, int | float)
                  or not 0 < minutes <= MAX_DAY_MIN):
                raise ValueError(f"Durée maximale de 1 à {MAX_DAY_MIN} min.")
            cleaned.append({"weekday": d["weekday"], "status": d["status"],
                            "max_min": int(minutes) if minutes is not None else None})
        availability = cleaned
    if "availability" in values:
        out["availability"] = availability
    habits = values.get("habits")
    if habits is not None:
        if not isinstance(habits, list):
            raise ValueError("Habitudes invalides.")
        habits = [{"weekday": int(h["weekday"]), "place": [float(h["place"][0]), float(h["place"][1])],
                   "name": str(h.get("name") or "").strip()[:tracked.NAME_MAX] or None,
                   "keep": bool(h.get("keep"))} for h in habits]
    if "habits" in values:
        out["habits"] = habits
    return out


def effective_habits(stored: list | None, detected: list[dict]) -> list[dict]:
    """Habitudes détectées, avec le choix de Greg (gardée ou non, nom) : une habitude enregistrée
    vaut pour le même jour et un lieu à moins de deux cases (le centre de la case bouge un peu
    d'une période à l'autre)."""
    out = []
    for h in detected:
        match = next((s for s in (stored or []) if s["weekday"] == h["weekday"]
                      and _distance_m(s["place"], h["place"]) <= 2 * PLACE_CELL_M), None)
        out.append({**h, "keep": match["keep"] if match else None, "confirmed": match is not None,
                    "label_name": (match or {}).get("name") or h["name"]})
    return out


# ---------- objectif proposé ----------

def proposed_target(cfg, race: dict, today: date, data: dict, factors: dict, dem=None) -> dict | None:
    """Temps réaliste de l'estimateur aujourd'hui (correction de l'admin comprise), avec sa
    fourchette : la proposition d'objectif."""
    result = tracked.predict(cfg, race, today, data, dem)
    if not result:
        return None
    factor = factors["trail" if race.get("gpx_id") else "road"]
    return {k: round(result[k] * factor) for k in ("optimistic_s", "realistic_s", "prudent_s")}
