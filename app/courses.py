"""
Courses : candidates détectées (races.py), décisions de Greg (table races), et pour chaque course
confirmée la forme du jour J (modèle de Banister) et l'allure face aux sorties habituelles.
"""
from datetime import UTC, date, datetime, timedelta

from . import metrics_job, queries, races, settings, stats


def _settings(conn) -> dict:
    s = settings.get(conn, "races")
    return {"keywords": s["keywords"] if s["keywords"] is not None else races.DEFAULT_KEYWORDS,
            "custom_keywords": s["keywords"] is not None, "threshold": s["threshold"]}


def _activities(conn):
    acts = queries.running_activities(conn)
    pos = queries.start_positions(conn)
    for a in acts:
        a["start_pos"] = pos.get(a["id"])
    return acts


def _summary(a) -> dict:
    return {"id": a["id"], "date": a["start"].date().isoformat(), "name": a["name"],
            "distance_km": round(a["distance_km"], 2), "gain_m": round(a["gain_m"]),
            "moving_s": a["moving_duration_s"], "elapsed_s": a.get("elapsed_s"), "terrain": a.get("terrain"),
            "pace_s_km": stats.pace_s_per_km(a["moving_duration_s"], a["distance_km"]),
            "avg_hr": round(a["avg_hr"]) if a["avg_hr"] else None}


def overview(config, conn) -> dict:
    """Pour l'admin : réglages, courses probables à valider, courses confirmées et rejetées."""
    cfg = _settings(conn)
    acts = _activities(conn)
    by_id = {a["id"]: a for a in acts}
    decisions = queries.race_decisions(conn)
    lthr = metrics_job.params_of(config, conn)["lthr"]
    found = races.candidates(acts, queries.best_efforts(conn), lthr, cfg["keywords"], cfg["threshold"])
    pending = [{**_summary(by_id[c["id"]]), "score": c["score"], "reasons": c["reasons"]}
               for c in found if c["id"] not in decisions]
    pending.sort(key=lambda c: c["date"], reverse=True)
    return {
        "settings": cfg,
        "default_keywords": races.DEFAULT_KEYWORDS,
        "pending": pending,
        "confirmed": sorted((_summary(by_id[i]) for i, st in decisions.items()
                             if st == "confirmed" and i in by_id), key=lambda r: r["date"], reverse=True),
        "rejected_count": sum(1 for st in decisions.values() if st == "rejected"),
    }


def decide(conn, activity_id: int, status: str | None):
    """Confirme ou rejette une course ; None efface la décision (la sortie redevient candidate)."""
    with conn:
        if status is None:
            conn.execute("DELETE FROM races WHERE activity_id=?", (activity_id,))
        else:
            if status not in ("confirmed", "rejected"):
                raise ValueError("statut attendu : confirmed ou rejected")
            if not conn.execute("SELECT 1 FROM activities WHERE id=?", (activity_id,)).fetchone():
                raise ValueError("sortie inconnue")
            conn.execute(
                "INSERT INTO races (activity_id, status, decided_at) VALUES (?, ?, ?)"
                " ON CONFLICT(activity_id) DO UPDATE SET status=excluded.status,"
                " decided_at=excluded.decided_at",
                (activity_id, status, datetime.now(UTC).replace(microsecond=0).isoformat()),
            )


def race_page(config, conn, today: date) -> dict:
    """Pour la page Courses : chaque course confirmée avec sa forme le jour J et son allure
    comparée aux sorties habituelles de même terrain et de distance comparable."""
    acts = _activities(conn)
    decisions = queries.race_decisions(conn)
    lthr = metrics_job.params_of(config, conn)["lthr"]
    daily = {}
    for a in acts:
        if a.get("hrss"):
            daily[a["start"].date()] = daily.get(a["start"].date(), 0.0) + a["hrss"]
    series = {p["date"]: p for p in stats.banister(daily, min(daily), today)} if daily else {}
    ctx = races.build_context(acts, [], lthr, [])
    out = []
    for a in acts:
        if decisions.get(a["id"]) != "confirmed":
            continue
        day = a["start"].date()
        p = series.get(day)
        before = series.get(day - timedelta(days=7))
        usual = races.usual_pace(a, ctx["acts"]) if a["distance_km"] > 1 and a["moving_duration_s"] else None
        pace = stats.pace_s_per_km(a["moving_duration_s"], a["distance_km"])
        out.append({
            **_summary(a),
            "fitness": round(p["fitness"], 1) if p else None,
            "form": round(p["form"], 1) if p else None,
            "form_zone": stats.form_zone(p["form"])[1] if p else None,
            "form_week_before": round(before["form"], 1) if before else None,
            "faster_than_usual_pct": round((1 - pace / usual) * 100, 1) if usual and pace else None,
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return {"races": out}
