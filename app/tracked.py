"""
Courses suivies par l'estimateur, indépendantes du coach (phase 3).

Une course suivie a un parcours (GPX importé, sinon distance et D+), une date et un objectif
facultatifs. Chaque semaine, la prédiction « si je courais maintenant » est enregistrée avec la
forme au soir du dimanche (lundi de la semaine − 1 jour) : le planificateur l'enregistre le lundi
après la synchro du jour. À l'ajout d'une course, les REPLAY_WEEKS semaines précédentes sont
rejouées (les calculs sont rejouables à n'importe quelle date) et marquées comme telles.

Les prédictions utilisent les périodes par défaut de l'estimateur (forme sur 12 semaines, modèle
allure-pente sur 12 mois), pas celles choisies sur la page, pour que la courbe reste comparable
d'une semaine à l'autre. Parcours GPX : estimateur trail (temps total, ravitos du parcours) ;
distance et D+ : estimateur route. Une fois la date passée, plus rien n'est enregistré.
"""
import math
from datetime import UTC, date, datetime, timedelta

from . import db, estimator, gpx_store, metrics_job, queries, settings, stats, trail

VERSION = f"route{estimator.ESTIMATE_VERSION}-trail{trail.TRAIL_VERSION}"
REPLAY_WEEKS = 12
EVOLUTION_WEEKS = 4
NAME_MAX = 120
MAX_DISTANCE_KM = 400
MAX_TARGET_S = 7 * 86400


def week_of(d: date) -> date:
    """Lundi de la semaine de d."""
    return d - timedelta(days=d.weekday())


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# ---------- saisie ----------

def clean(cfg, values: dict) -> dict:
    """Champs d'une course suivie, vérifiés ; ValueError si la saisie est invalide. Parcours : un
    GPX importé ou une distance en km (D+ facultatif) ; date AAAA-MM-JJ et objectif en secondes
    facultatifs."""
    if not isinstance(values, dict):
        raise ValueError("Saisie invalide.")
    name = str(values.get("name") or "").strip()[:NAME_MAX]
    if not name:
        raise ValueError("Donne un nom à la course.")
    race_date = values.get("race_date") or None
    if race_date is not None:
        try:
            race_date = date.fromisoformat(str(race_date)).isoformat()
        except ValueError:
            raise ValueError("Date attendue au format AAAA-MM-JJ.") from None
    gpx_id = values.get("gpx_id") or None
    distance_m = gain_m = None
    if gpx_id is not None:
        if not gpx_store.exists(cfg, str(gpx_id)):
            raise ValueError("Parcours GPX inconnu.")
    else:
        try:
            km = float(str(values.get("distance_km")).replace(",", "."))
            gain_m = float(str(values.get("gain_m") or 0).replace(",", "."))
        except ValueError:
            raise ValueError("Distance et D+ doivent être des nombres.") from None
        valid_gain = math.isfinite(gain_m) and gain_m >= 0
        if not (math.isfinite(km) and 0 < km <= MAX_DISTANCE_KM) or not valid_gain:
            raise ValueError(f"Distance de 0 à {MAX_DISTANCE_KM} km, D+ positif ou nul.")
        distance_m = km * 1000
    target = values.get("target_s")
    if target in (None, ""):
        target = None
    else:
        try:
            target = float(target)
        except (TypeError, ValueError):
            raise ValueError("Objectif invalide.") from None
        if not 0 < target <= MAX_TARGET_S:
            raise ValueError("Objectif invalide.")
    return {"name": name, "race_date": race_date, "gpx_id": gpx_id, "distance_m": distance_m,
            "gain_m": gain_m or 0.0, "target_s": target}


def create(conn, race: dict) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO tracked_races (name, race_date, gpx_id, distance_m, gain_m, target_s, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (race["name"], race["race_date"], race["gpx_id"], race["distance_m"], race["gain_m"],
             race["target_s"], _now()))
    return cur.lastrowid


def update(conn, race_id: int, race: dict) -> bool:
    """Modifie une course ; si son parcours change, ses prédictions sont effacées (à rejouer).
    Retourne True si le parcours a changé."""
    old = get(conn, race_id)
    if old is None:
        raise ValueError("Course inconnue.")
    changed = any(old[k] != race[k] for k in ("gpx_id", "distance_m", "gain_m"))
    with conn:
        conn.execute("UPDATE tracked_races SET name=?, race_date=?, gpx_id=?, distance_m=?, gain_m=?,"
                     " target_s=? WHERE id=?",
                     (race["name"], race["race_date"], race["gpx_id"], race["distance_m"], race["gain_m"],
                      race["target_s"], race_id))
        if changed:
            conn.execute("DELETE FROM tracked_predictions WHERE race_id=?", (race_id,))
    return changed


def delete(conn, race_id: int):
    with conn:
        conn.execute("DELETE FROM tracked_races WHERE id=?", (race_id,))


def get(conn, race_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tracked_races WHERE id=?", (race_id,)).fetchone()
    return dict(row) if row else None


def all_races(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tracked_races ORDER BY race_date IS NULL, race_date, id")]


def predictions(conn, race_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tracked_predictions WHERE race_id=? ORDER BY week", (race_id,))]


# ---------- prédictions ----------

def load_data(cfg, conn) -> dict:
    """Sorties, meilleurs efforts, courses confirmées et réglages de D+ : tout ce dont les
    estimateurs ont besoin."""
    return {"acts": queries.running_activities(conn), "efforts": queries.best_efforts(conn),
            "confirmed": {i for i, s in queries.race_decisions(conn).items() if s == "confirmed"},
            "params": settings.get(conn, "elevation"),
            "lthr": metrics_job.params_of(cfg, conn)["lthr"]}


def fitness_on(acts, day: date) -> float | None:
    daily = {d: v for d, v in estimator._daily_load(acts).items() if d <= day}
    return stats.banister(daily, min(daily), day)[-1]["fitness"] if daily else None


def predict(cfg, race: dict, day: date, data: dict, dem=None) -> dict | None:
    """Prédiction pour une course au soir de `day` : estimateur trail sur son GPX, sinon route ;
    None si l'estimateur ne peut pas conclure."""
    if race.get("gpx_id"):
        if not gpx_store.exists(cfg, race["gpx_id"]):
            return None
        lats, lons, eles, dem_profile = gpx_store.route(cfg, race["gpx_id"], dem)
        stations = gpx_store.meta(cfg, race["gpx_id"], stations=True)["aid_stations"]
        result = trail.estimate_gpx(lats, lons, eles, data["acts"], data["efforts"], day,
                                    dem_profile=dem_profile, params=data["params"], aid_stations=stations,
                                    race_ids=data["confirmed"])
        return None if result.get("error") else result
    return estimator.predict_road(data["efforts"], day, race["distance_m"], race["gain_m"] or 0.0)


def record(cfg, conn, today: date, race_ids=None, replay_weeks: int = 0, data: dict | None = None,
           dem=None) -> int:
    """Enregistre la prédiction de la semaine de `today` (et des `replay_weeks` précédentes) pour
    chaque course suivie encore à venir (ou celles de race_ids), si elle manque. Retourne le nombre
    de prédictions enregistrées."""
    week = week_of(today)
    weeks = [week - timedelta(weeks=k) for k in range(replay_weeks, -1, -1)]
    done = 0
    for race in all_races(conn):
        if race_ids is not None and race["id"] not in race_ids:
            continue
        if race["activity_id"]:
            continue                    # course courue : plus de prédiction
        have = {r["week"] for r in conn.execute("SELECT week FROM tracked_predictions WHERE race_id=?",
                                                 (race["id"],))}
        for w in weeks:
            if w.isoformat() in have or (race["race_date"] and w.isoformat() > race["race_date"]):
                continue
            data = data or load_data(cfg, conn)
            day = w - timedelta(days=1)
            p = predict(cfg, race, day, data, dem)
            if p is None:
                continue
            f = fitness_on(data["acts"], day)
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tracked_predictions (race_id, week, form_day, optimistic_s,"
                    " realistic_s, prudent_s, fitness, replayed, version, computed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (race["id"], w.isoformat(), day.isoformat(), p["optimistic_s"], p["realistic_s"],
                     p["prudent_s"], round(f, 1) if f is not None else None, int(w != week), VERSION, _now()))
            done += 1
    return done


def weekly_job(cfg, today: date, dem=None) -> int:
    """Tâche du planificateur : prédictions de la semaine manquantes."""
    conn = db.connect(cfg.db_path)
    try:
        return record(cfg, conn, today, dem=dem)
    finally:
        conn.close()


# ---------- affichage ----------

def _route_label(cfg, race) -> str:
    if race["gpx_id"]:
        return gpx_store.meta(cfg, race["gpx_id"])["name"] if gpx_store.exists(cfg, race["gpx_id"]) else "GPX"
    km = f"{race['distance_m'] / 1000:.1f}".replace(".", ",").removesuffix(",0")
    return f"{km} km" + (f", {round(race['gain_m'])} m D+" if race["gain_m"] else "")


def summary(cfg, conn, race: dict, today: date) -> dict:
    """Une course suivie pour la vue d'ensemble : dernière prédiction et évolution sur 4 semaines."""
    preds = predictions(conn, race["id"])
    last = preds[-1] if preds else None
    before = None
    if last:
        ref = (date.fromisoformat(last["week"]) - timedelta(weeks=EVOLUTION_WEEKS)).isoformat()
        before = next((p for p in reversed(preds) if p["week"] <= ref), None)
    days = (date.fromisoformat(race["race_date"]) - today).days if race["race_date"] else None
    return {**race, "route": _route_label(cfg, race), "kind": "trail" if race["gpx_id"] else "road",
            "days_left": days, "last": last, "before": before,
            "evolution_s": round(last["realistic_s"] - before["realistic_s"]) if last and before else None,
            "target_gap_s": (round(last["realistic_s"] - race["target_s"])
                             if last and race["target_s"] else None),
            "past": days is not None and days < 0}


def overview(cfg, conn, today: date) -> list[dict]:
    return [summary(cfg, conn, r, today) for r in all_races(conn)]
