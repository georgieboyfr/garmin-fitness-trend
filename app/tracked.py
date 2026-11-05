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

import numpy as np

from . import (
    courses,
    db,
    detail,
    estimator,
    gpx_store,
    hr_speed,
    metrics_job,
    queries,
    settings,
    stats,
    trail,
)
from .elevation import series_distance
from .series import read_series

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

def with_tested_vma(efforts: list[dict], conn) -> list[dict]:
    """Meilleurs efforts, plus la VMA testée saisie dans l'admin (demi-Cooper) comme effort route de
    6 min à cette vitesse, à la date du test : une référence de l'estimateur jusqu'à 15 km."""
    training = settings.get(conn, "training")
    kmh, day = training.get("vma_kmh"), training.get("vma_date")
    if not kmh or not day:
        return efforts
    return efforts + [{"terrain": "road", "kind": "vma_test", "key": estimator.VMA_TEST_S,
                       "value": kmh / 3.6 * estimator.VMA_TEST_S, "date": f"{day}T12:00:00", "id": None,
                       "name": "VMA testée (admin)", "avg_hr": None, "year": int(day[:4]),
                       "description": None, "extra": None, "start_time_local": None}]


def load_data(cfg, conn) -> dict:
    """Sorties, meilleurs efforts, courses confirmées, réglages de D+, LTHR et tendance FC / vitesse :
    tout ce dont les estimateurs ont besoin."""
    lthr = metrics_job.params_of(cfg, conn)["lthr"]
    return {"acts": queries.running_activities(conn),
            "efforts": with_tested_vma(queries.best_efforts(conn), conn),
            "confirmed": {i for i, s in queries.race_decisions(conn).items() if s == "confirmed"},
            "params": settings.get(conn, "elevation"), "lthr": lthr,
            "trend": hr_speed.SpeedTrend(queries.steady_blocks(conn), lthr)}


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
                                    race_ids=data["confirmed"], trend=data.get("trend"))
        return None if result.get("error") else result
    return estimator.predict_road(data["efforts"], day, race["distance_m"], race["gain_m"] or 0.0,
                                  trend=data.get("trend"))


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
        # semaines rejouées avec une ancienne version de l'estimateur : recalculées ; celles
        # enregistrées en temps réel gardent ce qui avait été prédit à l'époque
        stale = [date.fromisoformat(r["week"]) for r in conn.execute(
            "SELECT week FROM tracked_predictions WHERE race_id=? AND replayed=1 AND version!=?",
            (race["id"], VERSION))]
        have = {r["week"] for r in conn.execute(
            "SELECT week FROM tracked_predictions WHERE race_id=? AND (replayed=0 OR version=?)",
            (race["id"], VERSION))}
        for w in sorted(set(weeks) | set(stale)):
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


def race_profiles(cfg, acts, confirmed, params) -> list[tuple[dict, dict | None]]:
    """Courses trail confirmées et le profil de leur propre trace (altitude retenue pour le D+ :
    baromètre ou MNT), qui sert de GPX pour rejouer l'estimateur trail."""
    return [(a, activity_profile(cfg, a, params)) for a in acts
            if a["id"] in confirmed and a.get("terrain") == "trail"]


def activity_profile(cfg, a: dict, params, table=None) -> dict | None:
    """Profil de la trace d'une sortie (altitude retenue pour son D+ : baromètre ou MNT), qui sert
    de GPX pour y rejouer l'estimateur trail ; None sans série ou sans altitude."""
    try:
        table = table if table is not None else read_series(cfg.series_dir, a["id"])
        dist, alt = detail.retained_altitude(cfg, a["id"], table, a.get("elevation_source"))
        return trail.altitude_profile(dist, alt, a.get("elevation_source") or "dem", params)
    except (OSError, KeyError, ValueError):
        return None


# ---------- après la course : sortie reliée, écart, calibration ----------
#
# Une course suivie dont la date est passée est reliée à la sortie de course à pied du jour
# (± LINK_DAYS), de distance proche (± LINK_TOLERANCE) et, pour un GPX, partie à moins de
# LINK_START_M du départ du parcours ; la plus proche en distance l'emporte. La sortie est aussi
# confirmée comme course si Greg ne l'a pas déjà classée. Une sortie reliée ou déliée à la main
# n'est plus touchée.
#
# Calibration : sur le rejeu de toutes les courses confirmées (validation route et trail, forme
# de la veille, périodes par défaut), facteur = 1 / moyenne géométrique de (estimé / réel), proposé
# à partir de CALIBRATION_MIN courses par terrain. Greg l'active dans l'admin : le facteur est alors
# figé dans les réglages et multiplie tous les temps estimés de ce terrain, jusqu'à ce qu'il le
# mette à jour ou le retire. Les mesures de précision restent sans correction.

LINK_DAYS = 1
LINK_TOLERANCE = 0.15
LINK_START_M = 3000
CALIBRATION_MIN = 3


def race_distance(cfg, race: dict, params=None) -> float | None:
    """Distance du parcours (m) : saisie, ou celle du profil du GPX."""
    if not race["gpx_id"]:
        return race["distance_m"]
    if not gpx_store.exists(cfg, race["gpx_id"]):
        return None
    lats, lons, eles, dem_profile = gpx_store.route(cfg, race["gpx_id"])
    profile = trail.route_profile(lats, lons, eles, dem_profile, params)
    return float(profile["distance"][-1]) if profile else None


def _gpx_start(cfg, gpx_id: str):
    lats, lons, _, _ = gpx_store.route(cfg, gpx_id)
    return (lats[0], lons[0]) if lats else None


def _meters(a, b) -> float:
    dy = math.radians(a[0] - b[0]) * 6_371_000
    dx = math.radians(a[1] - b[1]) * 6_371_000 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def find_activity(cfg, race: dict, acts, starts: dict, params=None) -> dict | None:
    """Sortie correspondant à une course passée, ou None."""
    if not race["race_date"]:
        return None
    distance = race_distance(cfg, race, params)
    if not distance:
        return None
    day = date.fromisoformat(race["race_date"])
    start = _gpx_start(cfg, race["gpx_id"]) if race["gpx_id"] else None
    best = None
    for a in acts:
        if abs((a["start"].date() - day).days) > LINK_DAYS or not a.get("distance_m"):
            continue
        gap = abs(math.log(a["distance_m"] / distance))
        if gap > math.log(1 + LINK_TOLERANCE):
            continue
        if start and a["id"] in starts and _meters(start, starts[a["id"]]) > LINK_START_M:
            continue
        if best is None or gap < best[0]:
            best = (gap, a)
    return best[1] if best else None


def link_races(cfg, conn, today: date, data: dict | None = None) -> int:
    """Relie les courses suivies passées à leur sortie. Retourne le nombre de courses reliées."""
    pending = [r for r in all_races(conn) if not r["activity_id"] and not r["link_manual"]
               and r["race_date"] and r["race_date"] <= today.isoformat()]
    if not pending:
        return 0
    data = data or load_data(cfg, conn)
    starts = queries.start_positions(conn)
    decisions = queries.race_decisions(conn)
    done = 0
    for race in pending:
        a = find_activity(cfg, race, data["acts"], starts, data["params"])
        if a is None:
            continue
        set_activity(conn, race["id"], a["id"])
        if a["id"] not in decisions:
            courses.decide(conn, a["id"], "confirmed")
        done += 1
    return done


def set_activity(conn, race_id: int, activity_id: int | None, manual: bool = False):
    """Relie (ou délie) la sortie ; manual : choix de Greg, que la liaison automatique respecte."""
    with conn:
        conn.execute("UPDATE tracked_races SET activity_id=?, link_manual=? WHERE id=?",
                     (activity_id, int(manual), race_id))


def candidates(conn, race: dict, days: int = 3) -> list[dict]:
    """Sorties de course à pied autour de la date de la course, pour la relier à la main."""
    if not race["race_date"]:
        return []
    day = date.fromisoformat(race["race_date"])
    lo, hi = (day - timedelta(days=days)).isoformat(), (day + timedelta(days=days + 1)).isoformat()
    return [a for a in queries.running_activities(conn) if lo <= a["start_time_local"] < hi]


def _activity(conn, activity_id: int) -> dict | None:
    row = conn.execute(
        "SELECT a.id, a.start_time_local, a.distance_m, a.duration_s, n.name,"
        " COALESCE(m.elapsed_s, a.duration_s) AS elapsed_s FROM activities a"
        " JOIN activity_names n ON n.activity_id = a.id"
        " LEFT JOIN activity_metrics m ON m.activity_id = a.id WHERE a.id=?", (activity_id,)).fetchone()
    return dict(row) if row else None


def result(conn, race: dict, preds: list[dict]) -> dict | None:
    """Résultat d'une course courue face à la dernière prédiction enregistrée avant elle."""
    if not race["activity_id"]:
        return None
    a = _activity(conn, race["activity_id"])
    if a is None:
        return None
    day = a["start_time_local"][:10]
    before = [p for p in preds if p["week"] <= day]
    p = before[-1] if before else None
    actual = a["elapsed_s"]
    ok = bool(p and actual)
    return {"activity_id": a["id"], "name": a["name"], "date": day, "elapsed_s": round(actual or 0),
            "distance_km": round((a["distance_m"] or 0) / 1000, 1), "prediction": p,
            "error_pct": round((p["realistic_s"] / actual - 1) * 100, 1) + 0.0 if ok else None,
            "within": p["optimistic_s"] <= actual <= p["prudent_s"] if ok else None,
            "target_gap_s": round(actual - race["target_s"]) if race["target_s"] and actual else None}


def _proposal(rows, key) -> dict:
    ratios = [1 + r[key] / 100 for r in rows if r.get(key) is not None]
    if len(ratios) < CALIBRATION_MIN:
        return {"n": len(ratios), "factor": None, "bias_pct": None}
    mean = math.exp(sum(math.log(x) for x in ratios) / len(ratios))
    return {"n": len(ratios), "factor": round(1 / mean, 4), "bias_pct": round((mean - 1) * 100, 1) + 0.0}


def proposed_corrections(cfg, conn, data: dict | None = None) -> dict:
    """Correction proposée par terrain, d'après le rejeu des courses confirmées (périodes par défaut)."""
    data = data or load_data(cfg, conn)
    road = estimator.validate_road(data["acts"], data["efforts"], data["confirmed"], trend=data.get("trend"))
    trail_v = trail.validate_trail(race_profiles(cfg, data["acts"], data["confirmed"], data["params"]),
                                   data["acts"], data["efforts"], data["confirmed"], trend=data.get("trend"))
    return {"road": _proposal(road["races"], "error_pct"), "trail": _proposal(trail_v["races"], "error_pct")}


def corrections(conn) -> dict:
    """Facteurs de correction appliqués (réglages de l'admin), 1 par défaut."""
    s = settings.get(conn, "estimator")
    return {"road": s["correction_road"] or 1.0, "trail": s["correction_trail"] or 1.0}



# ---------- estimé et réel sur la trace d'une course (fiche de sortie) ----------

def estimate_vs_actual(cfg, conn, activity_id: int, today: date) -> dict:
    """L'estimateur trail rejoué sur la trace d'une sortie, avec la forme de la veille et celle
    d'aujourd'hui (temps totaux, part d'arrêt comprise, sans correction), et l'écart cumulé entre
    le temps réel (écoulé) et chaque estimation tous les 100 m : positif = en retard sur l'estimé.
    Les distances de la montre sont ramenées à celle du profil (MNT ou baromètre) au prorata."""
    data = load_data(cfg, conn)
    a = next((x for x in data["acts"] if x["id"] == activity_id), None)
    if a is None:
        return {"error": "Sortie inconnue."}
    try:
        table = read_series(cfg.series_dir, activity_id)
    except OSError:
        return {"error": "Pas de trace enregistrée pour cette sortie."}
    profile = activity_profile(cfg, a, data["params"], table)
    if profile is None:
        return {"error": "Trace sans altitude exploitable."}
    ts = table.column("timestamp").to_pylist()
    d = series_distance(table)
    t = np.array([(x - ts[0]).total_seconds() if x else np.nan for x in ts])
    ok = np.isfinite(d) & np.isfinite(t)
    if ok.sum() < 2:
        return {"error": "Trace sans distance ni temps."}
    d, t = np.maximum.accumulate(d[ok]), t[ok]
    estimates = []
    for key, label, day in (("eve", "Forme de la veille", a["start"].date() - timedelta(days=1)),
                            ("today", "Forme d'aujourd'hui", today)):
        model = estimator.grade_pace_model(data["acts"], day)
        r = None
        if model:
            r = trail.predict_trail(profile, model, data["efforts"], day,
                                    fatigue=trail.fatigue_exponent(data["acts"], model, day),
                                    stops=trail.stop_rate(data["acts"], data["confirmed"], day),
                                    trend=data.get("trend"))
        if r:
            estimates.append({"key": key, "label": label, "day": day.isoformat(), "chart": r["chart"],
                              **{k: r[k] for k in ("optimistic_s", "realistic_s", "prudent_s", "moving_s",
                                                   "stops_s", "reference", "fatigue")}})
    if not estimates:
        return {"error": "L'estimateur n'a pas pu conclure (pas d'effort route ou de modèle allure-pente)."}
    km = np.array(estimates[0]["chart"]["km"])
    actual = np.interp(km * 1000 / profile["distance"][-1] * d[-1], d, t)
    elapsed = a.get("elapsed_s") or float(t[-1])
    out = []
    for e in estimates:
        times = np.array(e.pop("chart")["time"], dtype=float)
        out.append({**e, "times": [round(float(x)) for x in times],
                    "gap": [round(float(x)) for x in actual - times],
                    "error_pct": round((e["realistic_s"] / elapsed - 1) * 100, 1) + 0.0})
    altitude = np.interp(km * 1000, profile["distance"], profile["altitude"])
    return {"activity_id": activity_id, "km": km.tolist(), "altitude": [round(float(v)) for v in altitude],
            "actual": [round(float(x)) for x in actual], "elapsed_s": round(elapsed), "estimates": out}

# ---------- affichage ----------

def _route_label(cfg, race) -> str:
    if race["gpx_id"]:
        return gpx_store.meta(cfg, race["gpx_id"])["name"] if gpx_store.exists(cfg, race["gpx_id"]) else "GPX"
    km = f"{race['distance_m'] / 1000:.1f}".replace(".", ",").removesuffix(",0")
    return f"{km} km" + (f", {round(race['gain_m'])} m D+" if race["gain_m"] else "")


def corrected(preds: list[dict], factor: float) -> list[dict]:
    """Prédictions enregistrées (brutes) avec la correction en vigueur."""
    if factor == 1.0:
        return preds
    return [{**p, **{k: round(p[k] * factor) for k in ("optimistic_s", "realistic_s", "prudent_s")}}
            for p in preds]


def summary(cfg, conn, race: dict, today: date, factors: dict | None = None) -> dict:
    """Une course suivie : dernière prédiction (corrigée si une correction est activée), évolution
    sur 4 semaines, et résultat une fois courue."""
    kind = "trail" if race["gpx_id"] else "road"
    factor = (factors or corrections(conn))[kind]
    preds = corrected(predictions(conn, race["id"]), factor)
    last = preds[-1] if preds else None
    before = None
    if last:
        ref = (date.fromisoformat(last["week"]) - timedelta(weeks=EVOLUTION_WEEKS)).isoformat()
        before = next((p for p in reversed(preds) if p["week"] <= ref), None)
    days = (date.fromisoformat(race["race_date"]) - today).days if race["race_date"] else None
    return {**race, "route": _route_label(cfg, race), "kind": kind, "factor": factor,
            "predictions": preds, "result": result(conn, race, preds),
            "days_left": days, "last": last, "before": before,
            "evolution_s": round(last["realistic_s"] - before["realistic_s"]) if last and before else None,
            "target_gap_s": (round(last["realistic_s"] - race["target_s"])
                             if last and race["target_s"] else None),
            "past": days is not None and days < 0}


def ahead_errors(races: list[dict]) -> dict | None:
    """Erreur des prédictions enregistrées en temps réel avant la course (pas rejouées) : la seule
    mesure qui ne doit rien au réglage de l'estimateur."""
    rows = [{"error_pct": r["result"]["error_pct"]} for r in races
            if r["result"] and r["result"]["prediction"] and not r["result"]["prediction"]["replayed"]]
    return estimator.error_summary(rows, "error_pct")


def overview(cfg, conn, today: date) -> list[dict]:
    link_races(cfg, conn, today)
    factors = corrections(conn)
    return [summary(cfg, conn, r, today, factors) for r in all_races(conn)]
