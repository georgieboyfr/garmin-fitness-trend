"""
Calcul et stockage des métriques des sorties de course à pied (voir metrics.py).

Une sortie est (re)calculée si elle n'a pas encore de métriques, si METRICS_VERSION a
changé, ou si les paramètres physiologiques du .env (FC repos, FC max, LTHR, sexe) ne
sont plus ceux utilisés. Le D+ doit être calculé avant (classement route ou trail).
"""
import json
import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from .metrics import activity_metrics
from .series import read_series
from .sports import RUNNING_TYPES

log = logging.getLogger("metrics")

METRICS_VERSION = 1


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def params_of(config) -> dict:
    return {"hr_rest": config.hr_rest, "hr_max": config.hr_max, "lthr": config.lthr, "sex": config.sex}


def _key(params) -> str:
    return json.dumps(params, sort_keys=True)


def pending_metrics(conn, config) -> list[int]:
    types = tuple(RUNNING_TYPES)
    return [r[0] for r in conn.execute(
        "SELECT a.id FROM activities a"
        " JOIN activity_series s ON s.activity_id = a.id AND s.status = 'ok'"
        " JOIN activity_elevation e ON e.activity_id = a.id"
        " LEFT JOIN activity_metrics m ON m.activity_id = a.id"
        f" WHERE a.deleted_in_garmin = 0 AND a.activity_type IN ({','.join('?' * len(types))})"
        " AND (m.activity_id IS NULL OR m.version < ? OR m.params != ?)"
        " ORDER BY a.start_time_utc",
        (*types, METRICS_VERSION, _key(params_of(config))),
    )]


def compute_pending(config, conn, progress=None) -> Counter:
    ids = pending_metrics(conn, config)
    counts = Counter()
    if not ids:
        return counts
    p = params_of(config)
    key = _key(p)
    gains = dict(conn.execute("SELECT activity_id, gain_m FROM activity_elevation").fetchall())
    log.info("Métriques de %d sortie(s)", len(ids))
    for index, activity_id in enumerate(ids, 1):
        if progress:
            progress("métriques des sorties", index, len(ids), str(activity_id))
        try:
            table = read_series(config.series_dir, activity_id,
                                ["timestamp", "distance_m", "lat", "lon", "heart_rate"])
            m = activity_metrics(table, gains.get(activity_id),
                                 p["hr_rest"], p["hr_max"], p["lthr"], p["sex"])
        except Exception as e:
            log.warning("Métriques de %s en erreur : %s", activity_id, e)
            counts["metrics_errors"] += 1
            continue
        with conn:
            conn.execute(
                "INSERT INTO activity_metrics (activity_id, elapsed_s, moving_s, avg_hr, max_hr, trimp, hrss,"
                " zone1_s, zone2_s, zone3_s, zone4_s, zone5_s, hr_best_20min, hr_best_30min, hr_best_60min,"
                " terrain, version, params, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(activity_id) DO UPDATE SET elapsed_s=excluded.elapsed_s,"
                " moving_s=excluded.moving_s, avg_hr=excluded.avg_hr, max_hr=excluded.max_hr,"
                " trimp=excluded.trimp, hrss=excluded.hrss, zone1_s=excluded.zone1_s,"
                " zone2_s=excluded.zone2_s, zone3_s=excluded.zone3_s, zone4_s=excluded.zone4_s,"
                " zone5_s=excluded.zone5_s, hr_best_20min=excluded.hr_best_20min,"
                " hr_best_30min=excluded.hr_best_30min, hr_best_60min=excluded.hr_best_60min,"
                " terrain=excluded.terrain, version=excluded.version, params=excluded.params,"
                " computed_at=excluded.computed_at",
                (activity_id, m["elapsed_s"], m["moving_s"], m["avg_hr"], m["max_hr"], m["trimp"], m["hrss"],
                 *m["zones_s"], m["hr_best_20min"], m["hr_best_30min"], m["hr_best_60min"], m["terrain"],
                 METRICS_VERSION, key, _now_iso()),
            )
        counts["metrics"] += 1
    log.info("Métriques calculées pour %d sortie(s)", counts["metrics"])
    return counts


def lthr_estimate(conn, today: date, days=365) -> dict:
    """Estimation de la LTHR : meilleure FC moyenne tenue une heure sur la période (un effort
    d'une heure à fond se court au seuil), et à titre indicatif la meilleure sur 30 min.
    N'est jamais appliquée automatiquement : la valeur de référence reste LTHR dans .env."""
    since = (today - timedelta(days=days)).isoformat()

    def best(column):
        row = conn.execute(
            f"SELECT m.{column}, a.start_time_local, a.id FROM activity_metrics m"
            " JOIN activities a ON a.id = m.activity_id"
            f" WHERE a.start_time_local >= ? AND m.{column} IS NOT NULL"
            f" ORDER BY m.{column} DESC LIMIT 1", (since,)).fetchone()
        return {"hr": round(row[0]), "date": row[1][:10], "activity_id": row[2]} if row else None

    max_hr = conn.execute(
        "SELECT MAX(m.max_hr) FROM activity_metrics m JOIN activities a ON a.id = m.activity_id"
        " WHERE a.start_time_local >= ?", (since,)).fetchone()[0]
    return {"days": days, "best_60min": best("hr_best_60min"), "best_30min": best("hr_best_30min"),
            "max_hr": round(max_hr) if max_hr else None}
