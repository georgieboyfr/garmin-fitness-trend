"""
D+ / D− des activités de course à pied, après la lecture des FIT.

Source d'altitude, décidée par le modèle de montre (table devices) :
- montre avec baromètre et altitude présente dans le FIT : l'altitude du FIT ;
- sinon, avec GPS : MNT interrogé le long de la trace (profil mis en cache dans
  dem/profiles/<id>.parquet : une activité n'est interrogée qu'une fois) ;
- sans GPS (tapis, indoor) : D+ = 0.

Hors de France, le MNT Copernicus est un modèle de surface (bâtiments compris) qui
surestime le D+ en ville : si l'activité est appariée à Strava, le D+ de Strava est
retenu à la place (source « strava »), et sert aussi quand il arrive après le calcul.

Chaque résultat est enregistré avec la version de l'algorithme et les réglages
utilisés : changer l'un ou l'autre fait tout recalculer, sans réinterroger le MNT.
"""
import json
import logging
from collections import Counter
from datetime import UTC, datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import settings
from .dem import DemUnavailable
from .elevation import ALGO_VERSION, gain_loss, resample_positions, series_distance
from .series import read_series
from .sports import RUNNING_TYPES

log = logging.getLogger("elevation")

DEM_STEP_M = 10.0   # pas du profil MNT mis en cache (le calcul peut rééchantillonner plus large)
MIN_DEM_POINTS = 2


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_params(conn) -> dict:
    return settings.get(conn, "elevation")


def _params_key(params: dict) -> str:
    return json.dumps(params, sort_keys=True)


def pending_elevation(conn) -> list[int]:
    key = _params_key(current_params(conn))
    types = tuple(RUNNING_TYPES)
    return [r[0] for r in conn.execute(
        "SELECT a.id FROM activities a"
        " JOIN activity_series s ON s.activity_id = a.id AND s.status = 'ok'"
        " LEFT JOIN activity_elevation e ON e.activity_id = a.id"
        f" WHERE a.deleted_in_garmin = 0 AND a.activity_type IN ({','.join('?' * len(types))})"
        " AND (e.activity_id IS NULL OR e.algo_version < ? OR e.params != ?"
        "      OR (e.source = 'dem' AND e.dem_provider LIKE '%copernicus%' AND EXISTS ("
        "          SELECT 1 FROM strava_activities st WHERE st.activity_id = a.id"
        "          AND st.elevation_gain_m IS NOT NULL)))"
        " ORDER BY a.start_time_utc",
        (*types, ALGO_VERSION, key),
    )]


# ---------- profil MNT ----------

def dem_profile_path(config, activity_id):
    return config.dem_dir / "profiles" / f"{activity_id}.parquet"


def dem_profile(config, dem, activity_id, table):
    """(distance, altitude, fournisseur) du MNT le long de la trace, depuis le cache si possible."""
    path = dem_profile_path(config, activity_id)
    if path.exists():
        cached = pq.read_table(path)
        meta = cached.schema.metadata or {}
        if float(meta.get(b"step_m", b"0")) == DEM_STEP_M:
            return (cached["distance_m"].to_numpy(), cached["altitude_m"].to_numpy(),
                    meta.get(b"provider", b"").decode())
    lat = table.column("lat").to_numpy(zero_copy_only=False).astype(float)
    lon = table.column("lon").to_numpy(zero_copy_only=False).astype(float)
    dist, la, lo = resample_positions(series_distance(table), lat, lon, DEM_STEP_M)
    if dist.size < MIN_DEM_POINTS:
        return dist, np.zeros(0), ""
    alt, provider = dem.elevations(la, lo)
    ok = np.isfinite(alt)
    dist, alt = dist[ok], alt[ok]
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pa.table({"distance_m": dist, "altitude_m": alt.astype(np.float32)})
    out = out.replace_schema_metadata({"step_m": str(DEM_STEP_M), "provider": provider})
    tmp = path.with_name(path.name + ".part")
    pq.write_table(out, tmp, compression="zstd")
    tmp.replace(path)
    return dist, alt, provider


# ---------- calcul ----------

def compute_activity(config, dem, activity_id, has_barometer: bool, params: dict,
                     strava_gain: float | None = None) -> dict:
    table = read_series(config.series_dir, activity_id, ["distance_m", "lat", "lon", "altitude_m"])
    has_gps = table.column("lat").null_count < table.num_rows
    has_alt = table.column("altitude_m").null_count < table.num_rows
    common = (params["step_m"], params["window"])
    if has_barometer and has_alt:
        alt = table.column("altitude_m").to_numpy(zero_copy_only=False).astype(float)
        gain, loss = gain_loss(series_distance(table), alt, *common, params["threshold_barometer"])
        return {"source": "barometer", "dem_provider": None, "gain_m": gain, "loss_m": loss}
    if has_gps:
        dist, alt, provider = dem_profile(config, dem, activity_id, table)
        if "copernicus" in provider and strava_gain is not None:
            return {"source": "strava", "dem_provider": provider, "gain_m": strava_gain, "loss_m": None}
        if alt.size >= MIN_DEM_POINTS:
            gain, loss = gain_loss(dist, alt, *common, params["threshold_dem"])
            return {"source": "dem", "dem_provider": provider, "gain_m": gain, "loss_m": loss}
    return {"source": "none", "dem_provider": None, "gain_m": 0.0, "loss_m": 0.0}


def compute_pending(config, conn, dem, progress=None) -> Counter:
    ids = pending_elevation(conn)
    counts = Counter()
    if not ids:
        return counts
    params = current_params(conn)
    key = _params_key(params)
    barometer = {r[0]: bool(r[1]) for r in conn.execute(
        "SELECT a.id, COALESCE(d.has_barometer, 0) FROM activities a"
        " LEFT JOIN devices d ON d.garmin_product = a.garmin_product"
    )}
    strava_gains = dict(conn.execute(
        "SELECT activity_id, elevation_gain_m FROM strava_activities"
        " WHERE activity_id IS NOT NULL AND elevation_gain_m IS NOT NULL").fetchall())
    log.info("Calcul du D+ de %d activité(s)", len(ids))
    for index, activity_id in enumerate(ids, 1):
        if progress:
            progress("calcul du D+", index, len(ids), str(activity_id))
        try:
            r = compute_activity(config, dem, activity_id, barometer.get(activity_id, False), params,
                                 strava_gains.get(activity_id))
        except DemUnavailable as e:
            # le réseau reviendra : l'activité reste en attente pour la prochaine synchro
            log.warning("D+ de %s reporté : %s", activity_id, e)
            counts["elevation_postponed"] += 1
            continue
        with conn:
            conn.execute(
                "INSERT INTO activity_elevation (activity_id, source, dem_provider, gain_m, loss_m,"
                " algo_version, params, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(activity_id) DO UPDATE SET source=excluded.source,"
                " dem_provider=excluded.dem_provider, gain_m=excluded.gain_m, loss_m=excluded.loss_m,"
                " algo_version=excluded.algo_version, params=excluded.params,"
                " computed_at=excluded.computed_at",
                (activity_id, r["source"], r["dem_provider"], round(r["gain_m"], 1),
                 None if r["loss_m"] is None else round(r["loss_m"], 1), ALGO_VERSION, key, _now_iso()),
            )
        counts["elevation"] += 1
    log.info("D+ calculé pour %d activité(s), %d reportée(s)",
             counts["elevation"], counts["elevation_postponed"])
    return counts
