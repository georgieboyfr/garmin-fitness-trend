"""
Altitude du terrain (MNT) en des points (lat, lon).

- France : service de calcul altimétrique de l'IGN (Géoplateforme), ressource
  RGE ALTI (ign_rge_alti_wld). Gratuit, sans clé, 5 requêtes/s par adresse IP.
  Hors couverture, il renvoie -99999.
- Ailleurs : Copernicus GLO-30, dalles de 1° x 1° (GeoTIFF) téléchargées une fois
  depuis le dépôt public AWS dans dem/copernicus/, lues avec tifffile.

Chaque activité n'est interrogée qu'une fois : le profil obtenu est mis en cache
(voir elevation_job.py).
"""
import json
import logging
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

log = logging.getLogger("dem")

IGN_URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
IGN_RESOURCE = "ign_rge_alti_wld"
IGN_BATCH = 2000
IGN_MIN_INTERVAL_S = 0.25          # 4 requêtes/s, sous la limite de 5
IGN_NODATA = -99999.0
RETRY_PAUSES_S = (5, 30)

COPERNICUS_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif")


class DemUnavailable(RuntimeError):
    """Le MNT n'a pas pu être interrogé (réseau...) : à retenter plus tard."""


def _post_json(url, payload, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class IgnDem:
    name = "ign"

    def __init__(self, post_json=_post_json, sleep=time.sleep, clock=time.monotonic):
        self.post_json = post_json
        self.sleep = sleep
        self.clock = clock
        self._last = -math.inf

    def _request(self, payload):
        """Un appel, avec deux nouvelles tentatives espacées en cas de coupure réseau passagère."""
        for attempt, pause in enumerate(RETRY_PAUSES_S + (None,)):
            try:
                return self.post_json(IGN_URL, payload)["elevations"]
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
                if pause is None:
                    raise DemUnavailable(f"service altimétrique IGN indisponible : {e}") from e
                log.warning("Service altimétrique IGN, essai %d échoué (%s), nouvel essai dans %ds",
                            attempt + 1, e, pause)
                self.sleep(pause)
            finally:
                self._last = self.clock()

    def elevations(self, lats, lons) -> np.ndarray:
        """Altitudes (NaN hors couverture)."""
        out = np.full(len(lats), np.nan)
        for start in range(0, len(lats), IGN_BATCH):
            wait = IGN_MIN_INTERVAL_S - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
            sl = slice(start, start + IGN_BATCH)
            payload = {
                "lon": "|".join(f"{v:.6f}" for v in lons[sl]),
                "lat": "|".join(f"{v:.6f}" for v in lats[sl]),
                "resource": IGN_RESOURCE, "zonly": "true",
            }
            z = self._request(payload)
            z = np.asarray(z, dtype=float)
            z[z <= IGN_NODATA + 1] = np.nan
            out[sl] = z
        return out


def _download(url, path: Path, timeout=300):
    tmp = path.with_name(path.name + ".part")
    with urllib.request.urlopen(url, timeout=timeout) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(path)


class CopernicusDem:
    name = "copernicus"

    def __init__(self, tile_dir, download=_download):
        self.tile_dir = Path(tile_dir)
        self.download = download
        self._cache = {}   # une seule dalle en mémoire (52 Mo)

    @staticmethod
    def tile_name(lat_floor, lon_floor) -> str:
        ns = f"N{lat_floor:02d}" if lat_floor >= 0 else f"S{-lat_floor:02d}"
        ew = f"E{lon_floor:03d}" if lon_floor >= 0 else f"W{-lon_floor:03d}"
        return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"

    def _tile(self, lat_floor, lon_floor):
        key = (lat_floor, lon_floor)
        if key in self._cache:
            return self._cache[key]
        name = self.tile_name(lat_floor, lon_floor)
        path = self.tile_dir / f"{name}.tif"
        missing = self.tile_dir / f"{name}.absent"   # dalle inexistante (mer)
        array = None
        if not path.exists() and not missing.exists():
            self.tile_dir.mkdir(parents=True, exist_ok=True)
            try:
                log.info("Téléchargement de la dalle Copernicus %s", name)
                self.download(COPERNICUS_URL.format(name=name), path)
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    missing.touch()
                else:
                    raise DemUnavailable(f"dalle Copernicus {name} : {e}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                raise DemUnavailable(f"dalle Copernicus {name} : {e}") from e
        if path.exists():
            import tifffile
            array = tifffile.imread(path).astype(np.float32)
        self._cache = {key: array}
        return array

    def elevations(self, lats, lons) -> np.ndarray:
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        out = np.full(lats.size, np.nan)
        lat_f = np.floor(lats).astype(int)
        lon_f = np.floor(lons).astype(int)
        for key in sorted(set(zip(lat_f.tolist(), lon_f.tolist(), strict=True))):
            sel = (lat_f == key[0]) & (lon_f == key[1])
            tile = self._tile(*key)
            if tile is None:
                continue
            h, w = tile.shape
            # la dalle couvre [lat, lat+1] x [lon, lon+1], première ligne au nord
            r = (key[0] + 1 - lats[sel]) * h
            c = (lons[sel] - key[1]) * w
            out[sel] = _bilinear(tile, r - 0.5, c - 0.5)
        return out


def _bilinear(a, r, c):
    h, w = a.shape
    r = np.clip(r, 0, h - 1)
    c = np.clip(c, 0, w - 1)
    r0 = np.floor(r).astype(int)
    c0 = np.floor(c).astype(int)
    r1 = np.minimum(r0 + 1, h - 1)
    c1 = np.minimum(c0 + 1, w - 1)
    fr = r - r0
    fc = c - c0
    top = a[r0, c0] * (1 - fc) + a[r0, c1] * fc
    bottom = a[r1, c0] * (1 - fc) + a[r1, c1] * fc
    return top * (1 - fr) + bottom * fr


class Dem:
    """IGN d'abord, Copernicus pour les points hors couverture IGN."""

    def __init__(self, ign: IgnDem, copernicus: CopernicusDem):
        self.ign = ign
        self.copernicus = copernicus

    def elevations(self, lats, lons) -> tuple[np.ndarray, str]:
        """Retourne (altitudes, fournisseur : ign, copernicus ou ign+copernicus)."""
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        z = self.ign.elevations(lats, lons)
        missing = np.isnan(z)
        if not missing.any():
            return z, "ign"
        z[missing] = self.copernicus.elevations(lats[missing], lons[missing])
        return z, "copernicus" if missing.all() else "ign+copernicus"
