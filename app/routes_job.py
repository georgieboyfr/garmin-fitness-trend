"""
Signatures des traces et regroupement en parcours (voir routes.py), après les métriques.

Une signature n'est calculée qu'une fois par sortie (et à chaque nouvelle ROUTES_VERSION) ;
le regroupement, lui, est refait à chaque passage, en quelques secondes.
"""
import logging
from collections import Counter

import numpy as np

from . import routes
from .elevation import series_distance
from .series import read_series
from .sports import RUNNING_TYPES

log = logging.getLogger("routes")

ROUTES_VERSION = 1


def _missing(conn) -> list[int]:
    types = tuple(RUNNING_TYPES)
    return [r[0] for r in conn.execute(
        "SELECT a.id FROM activities a"
        " JOIN activity_series s ON s.activity_id = a.id AND s.status = 'ok' AND s.has_gps = 1"
        " LEFT JOIN activity_tracks t ON t.activity_id = a.id"
        f" WHERE a.deleted_in_garmin = 0 AND a.activity_type IN ({','.join('?' * len(types))})"
        " AND (t.activity_id IS NULL OR t.version < ?)",
        (*types, ROUTES_VERSION),
    )]


def compute(config, conn, progress=None) -> Counter:
    counts = Counter()
    missing = _missing(conn)
    for index, activity_id in enumerate(missing, 1):
        if progress:
            progress("tracés des sorties", index, len(missing), str(activity_id))
        table = read_series(config.series_dir, activity_id, ["distance_m", "lat", "lon"])
        dist = series_distance(table)
        sig = routes.signature(dist, table.column("lat").to_numpy(zero_copy_only=False),
                               table.column("lon").to_numpy(zero_copy_only=False))
        if sig is None:
            continue
        finite = dist[np.isfinite(dist)]
        with conn:
            conn.execute(
                "INSERT INTO activity_tracks (activity_id, version, distance_m, signature)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(activity_id) DO UPDATE SET version=excluded.version,"
                " distance_m=excluded.distance_m, signature=excluded.signature",
                (activity_id, ROUTES_VERSION, float(finite.max() - finite.min()),
                 sig.astype(np.float64).tobytes()),
            )
        counts["tracks"] += 1

    tracks = [{"id": r[0], "distance_m": r[1], "sig": np.frombuffer(r[2], dtype=np.float64).reshape(-1, 2)}
              for r in conn.execute(
                  "SELECT t.activity_id, t.distance_m, t.signature FROM activity_tracks t"
                  " JOIN activities a ON a.id = t.activity_id"
                  " LEFT JOIN activity_metrics m ON m.activity_id = a.id"
                  " WHERE a.deleted_in_garmin = 0 AND COALESCE(m.terrain, '') != 'indoor'"
                  " ORDER BY a.start_time_utc")]
    assignment = routes.cluster(tracks)
    with conn:
        conn.execute("DELETE FROM activity_routes")
        conn.executemany("INSERT INTO activity_routes (activity_id, route_id) VALUES (?, ?)",
                         list(assignment.items()))
    shared = Counter(assignment.values())
    log.info("%d sorties regroupées en %d parcours (%d parcours courus plusieurs fois)",
             len(assignment), len(shared), sum(1 for n in shared.values() if n > 1))
    return counts
