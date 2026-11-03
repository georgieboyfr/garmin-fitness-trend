"""Lecture des activités de course à pied pour les pages de statistiques."""
from datetime import datetime

from .sports import RUNNING_TYPES


def running_activities(conn) -> list[dict]:
    """Toutes les sorties de course à pied (Garmin et importées de Strava), de la plus ancienne
    à la plus récente, avec le nom affiché et le D+ recalculé."""
    types = tuple(RUNNING_TYPES)
    rows = conn.execute(
        "SELECT a.id, a.source, a.start_time_local, a.activity_type, n.name, n.description,"
        " a.distance_m, a.duration_s, COALESCE(m.moving_s, a.moving_duration_s) AS moving_duration_s,"
        " COALESCE(m.avg_hr, a.avg_hr) AS avg_hr, COALESCE(m.max_hr, a.max_hr) AS max_hr,"
        " e.gain_m, e.loss_m, e.source AS elevation_source, m.hrss, m.terrain, m.ef, m.decoupling_pct,"
        " m.gap_pace_s_km, m.grade_bins,"
        " m.zone1_s, m.zone2_s, m.zone3_s, m.zone4_s, m.zone5_s, m.elapsed_s, r.route_id"
        " FROM activities a"
        " JOIN activity_names n ON n.activity_id = a.id"
        " LEFT JOIN activity_elevation e ON e.activity_id = a.id"
        " LEFT JOIN activity_metrics m ON m.activity_id = a.id"
        " LEFT JOIN activity_routes r ON r.activity_id = a.id"
        f" WHERE a.deleted_in_garmin = 0 AND a.activity_type IN ({','.join('?' * len(types))})"
        " ORDER BY a.start_time_local",
        types,
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["start"] = datetime.fromisoformat(d["start_time_local"])
        d["distance_km"] = (d["distance_m"] or 0) / 1000
        d["gain_m"] = d["gain_m"] or 0.0
        d["elapsed_s"] = d["elapsed_s"] or d["duration_s"]
        out.append(d)
    return out


def best_efforts(conn) -> list[dict]:
    """Meilleurs efforts de chaque sortie de course (activity_bests), avec la sortie et son terrain."""
    types = tuple(RUNNING_TYPES)
    rows = conn.execute(
        "SELECT b.kind, b.key, b.value, b.extra, b.avg_hr, a.id, a.start_time_local, n.name, n.description,"
        " m.terrain"
        " FROM activity_bests b"
        " JOIN activities a ON a.id = b.activity_id"
        " JOIN activity_names n ON n.activity_id = a.id"
        " JOIN activity_metrics m ON m.activity_id = a.id"
        f" WHERE a.deleted_in_garmin = 0 AND a.activity_type IN ({','.join('?' * len(types))})",
        types,
    ).fetchall()
    return [dict(r) | {"year": int(r["start_time_local"][:4]), "date": r["start_time_local"][:10]}
            for r in rows]


def start_positions(conn) -> dict[int, tuple[float, float]]:
    """Point de départ de chaque sortie (premier point de la signature de sa trace)."""
    import struct

    return {r[0]: struct.unpack("<2d", r[1][:16]) for r in conn.execute(
        "SELECT activity_id, signature FROM activity_tracks")}


def race_decisions(conn) -> dict[int, str]:
    return dict(conn.execute("SELECT activity_id, status FROM races").fetchall())


def steady_blocks(conn) -> list[tuple[str, float, float]]:
    """Minutes stables (date, vitesse ajustée en m/s, FC) de toutes les sorties hors tapis, pour la
    relation FC / vitesse (hr_speed)."""
    import json

    return [(r[0][:10], v, h) for r in conn.execute(
        "SELECT x.start_time_local, m.steady_blocks FROM activity_metrics m"
        " JOIN activities x ON x.id = m.activity_id"
        " WHERE m.steady_blocks IS NOT NULL AND m.terrain != 'indoor' AND x.deleted_in_garmin = 0")
        for v, h in json.loads(r[1])]

