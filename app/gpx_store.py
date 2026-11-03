"""
Parcours GPX importés dans l'estimateur (data/gpx) : le GPX brut sous l'empreinte de son contenu,
ses métadonnées (nom, date d'import, ravitos) et l'altitude du MNT le long de la trace, mise en
cache pour n'interroger le MNT qu'une fois par parcours.
"""
import json
import re

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import trail
from .track_parser import parse_route, parse_waypoints

GPX_ID = re.compile(r"[0-9a-f]{16}")
GPX_RECENT = 8


def exists(cfg, gpx_id: str | None) -> bool:
    return bool(gpx_id) and bool(GPX_ID.fullmatch(gpx_id)) and (cfg.gpx_dir / f"{gpx_id}.gpx").exists()


def meta(cfg, gpx_id: str, stations: bool = False) -> dict:
    """Nom et date d'import d'un parcours ; avec stations, ses ravitos (enregistrés, sinon proposés
    d'après les waypoints du GPX)."""
    path = cfg.gpx_dir / f"{gpx_id}.json"
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = {"id": gpx_id, "name": stored.get("name") or "Parcours", "uploaded_at": stored.get("uploaded_at")}
    if stations:
        if "aid_stations" in stored:
            out["aid_stations"], out["aid_saved"] = stored["aid_stations"], True
        else:
            data = (cfg.gpx_dir / f"{gpx_id}.gpx").read_bytes()
            lats, lons, _ = parse_route(data)
            out["aid_stations"] = trail.waypoint_stations(lats, lons, parse_waypoints(data))
            out["aid_saved"] = False
    return out


def dem_profile(cfg, gpx_id: str, lats, lons, dem=None) -> dict | None:
    """Altitudes du MNT le long du parcours, depuis le cache (data/gpx/<id>.dem.parquet) ou, avec
    `dem`, interrogées puis mises en cache ; None sans MNT."""
    path = cfg.gpx_dir / f"{gpx_id}.dem.parquet"
    if path.exists():
        t = pq.read_table(path)
        return {"distance": t["distance_m"].to_numpy(), "altitude": t["altitude_m"].to_numpy().astype(float),
                "source": (t.schema.metadata or {}).get(b"provider", b"").decode()}
    profile = trail.dem_altitudes(dem, lats, lons) if dem is not None else None
    if profile is not None:
        table = pa.table({"distance_m": profile["distance"],
                          "altitude_m": profile["altitude"].astype(np.float32)})
        pq.write_table(table.replace_schema_metadata({"provider": profile["source"]}), path)
    return profile


def recent(cfg) -> list[dict]:
    """Derniers GPX importés, du plus récent au plus ancien."""
    if not cfg.gpx_dir.exists():
        return []
    files = sorted(cfg.gpx_dir.glob("*.gpx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [meta(cfg, p.stem) for p in files[:GPX_RECENT] if GPX_ID.fullmatch(p.stem)]


def route(cfg, gpx_id: str, dem=None):
    """(latitudes, longitudes, altitudes du GPX, profil du MNT ou None) d'un parcours."""
    lats, lons, eles = parse_route((cfg.gpx_dir / f"{gpx_id}.gpx").read_bytes())
    return lats, lons, eles, dem_profile(cfg, gpx_id, lats, lons, dem)
