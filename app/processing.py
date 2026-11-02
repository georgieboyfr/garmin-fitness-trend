"""
Traitements locaux après la synchro, à partir des FIT stockés (aucun appel à Garmin).

Lecture des FIT : chaque activité dont le FIT est stocké et qui n'a pas encore été
lue avec la version courante du lecteur est lue, sa série écrite en Parquet et le
modèle de montre enregistré. Une lecture en échec n'est retentée qu'à la version
suivante du lecteur. Les lectures sont réparties sur plusieurs processus.
"""
import logging
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime

from .fit_parser import PARSER_VERSION, parse_fit
from .series import write_series

log = logging.getLogger("processing")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_one(args):
    """Exécuté dans un processus séparé : lit le FIT et écrit la série."""
    activity_id, fit_path, series_dir = args
    try:
        data = parse_fit(fit_path)
        write_series(series_dir, activity_id, data.table)
        return activity_id, {
            "status": "ok", "garmin_product": data.garmin_product, "n_points": data.n_points,
            "has_gps": data.has("lat"), "has_altitude": data.has("altitude_m"),
            "has_hr": data.has("heart_rate"), "error": None,
        }
    except Exception as e:
        return activity_id, {"status": "error", "error": f"{e.__class__.__name__}: {e}"[:1000]}


def pending_parse(conn) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT a.id FROM activities a LEFT JOIN activity_series s ON s.activity_id = a.id"
        " WHERE a.fit_status = 'stored' AND (s.activity_id IS NULL OR s.parser_version < ?)"
        " ORDER BY a.start_time_utc",
        (PARSER_VERSION,),
    )]


def _store_result(conn, activity_id, r):
    with conn:
        conn.execute(
            "INSERT INTO activity_series (activity_id, parser_version, status, n_points, has_gps,"
            " has_altitude, has_hr, error, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(activity_id) DO UPDATE SET parser_version=excluded.parser_version,"
            " status=excluded.status, n_points=excluded.n_points, has_gps=excluded.has_gps,"
            " has_altitude=excluded.has_altitude, has_hr=excluded.has_hr, error=excluded.error,"
            " parsed_at=excluded.parsed_at",
            (activity_id, PARSER_VERSION, r["status"], r.get("n_points"), r.get("has_gps"),
             r.get("has_altitude"), r.get("has_hr"), r["error"], _now_iso()),
        )
        if r.get("garmin_product") is not None:
            conn.execute("UPDATE activities SET garmin_product=? WHERE id=?",
                         (r["garmin_product"], activity_id))


def parse_pending(config, conn, progress=None, workers=None) -> Counter:
    """Lit les FIT en attente. progress(stage, index, total, detail) est appelé au fil de l'eau."""
    ids = pending_parse(conn)
    counts = Counter()
    if not ids:
        return counts
    jobs = [(i, str(config.fit_dir / f"{i}.fit"), str(config.series_dir)) for i in ids]
    workers = workers or min(4, os.cpu_count() or 1)
    log.info("Lecture de %d FIT (%d processus)", len(ids), workers)

    def handle(index, activity_id, r):
        _store_result(conn, activity_id, r)
        counts["parsed" if r["status"] == "ok" else "parse_errors"] += 1
        if r["status"] != "ok":
            log.warning("Lecture du FIT %s en erreur : %s", activity_id, r["error"])
        if progress:
            progress("lecture des FIT", index, len(ids), str(activity_id))

    if workers == 1 or len(ids) == 1:
        for index, job in enumerate(jobs, 1):
            handle(index, *_parse_one(job))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for index, (activity_id, r) in enumerate(pool.map(_parse_one, jobs, chunksize=4), 1):
                handle(index, activity_id, r)
    log.info("Lecture des FIT terminée : %d lu(s), %d erreur(s)", counts["parsed"], counts["parse_errors"])
    return counts
