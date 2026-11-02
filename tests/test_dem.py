import urllib.error

import numpy as np
import pytest
import tifffile

from app.dem import IGN_BATCH, CopernicusDem, Dem, DemUnavailable, IgnDem


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_ign_batches_and_nodata():
    calls = []

    def post(url, payload):
        n = len(payload["lat"].split("|"))
        calls.append(n)
        return {"elevations": [212.5] * (n - 1) + [-99999.0]}

    sleeps = []
    dem = IgnDem(post_json=post, sleep=sleeps.append, clock=Clock())
    n = IGN_BATCH + 10
    z = dem.elevations(np.full(n, 45.19), np.full(n, 5.72))
    assert calls == [IGN_BATCH, 10]
    assert z[0] == 212.5
    assert np.isnan(z[IGN_BATCH - 1]) and np.isnan(z[-1])
    assert sleeps  # respect du débit entre deux requêtes


def test_ign_retries_then_gives_up():
    attempts = []

    def post(url, payload):
        attempts.append(1)
        raise urllib.error.URLError("getaddrinfo failed")

    sleeps = []
    dem = IgnDem(post_json=post, sleep=sleeps.append, clock=Clock())
    with pytest.raises(DemUnavailable):
        dem.elevations([45.19], [5.72])
    assert len(attempts) == 3 and 5 in sleeps and 30 in sleeps


def test_ign_recovers_after_transient_error():
    attempts = []

    def post(url, payload):
        attempts.append(1)
        if len(attempts) == 1:
            raise urllib.error.URLError("coupure")
        return {"elevations": [300.0]}

    dem = IgnDem(post_json=post, sleep=lambda s: None, clock=Clock())
    assert dem.elevations([45.19], [5.72])[0] == 300.0


def test_copernicus_tile_name():
    assert CopernicusDem.tile_name(41, 12) == "Copernicus_DSM_COG_10_N41_00_E012_00_DEM"
    assert CopernicusDem.tile_name(40, -4) == "Copernicus_DSM_COG_10_N40_00_W004_00_DEM"
    assert CopernicusDem.tile_name(-13, -63) == "Copernicus_DSM_COG_10_S13_00_W063_00_DEM"


def test_copernicus_download_once_and_interpolate(tmp_path):
    # dalle de test 10x10 : altitude = 100 + 10 x numéro de colonne (croît vers l'est)
    tile = (100 + 10 * np.tile(np.arange(10), (10, 1))).astype(np.float32)
    downloads = []

    def download(url, path):
        downloads.append(url)
        tifffile.imwrite(path, tile)

    dem = CopernicusDem(tmp_path, download=download)
    z = dem.elevations([41.55, 41.55], [12.05, 12.55])
    assert z[0] == pytest.approx(100, abs=0.5)      # première colonne
    assert z[1] == pytest.approx(150, abs=0.5)      # milieu de la dalle
    dem2 = CopernicusDem(tmp_path, download=download)
    dem2.elevations([41.5], [12.5])
    assert len(downloads) == 1 and "N41_00_E012" in downloads[0]


def test_copernicus_missing_tile_is_remembered(tmp_path):
    calls = []

    def download(url, path):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "absent", None, None)

    dem = CopernicusDem(tmp_path, download=download)
    assert np.isnan(dem.elevations([43.0], [5.0])[0])
    assert np.isnan(CopernicusDem(tmp_path, download=download).elevations([43.0], [5.0])[0])
    assert len(calls) == 1


def test_dem_falls_back_to_copernicus_outside_france():
    class Ign:
        def elevations(self, lats, lons):
            return np.array([200.0 if lo > 0 else np.nan for lo in lons])

    class Cop:
        def elevations(self, lats, lons):
            return np.full(len(lats), 650.0)

    dem = Dem(Ign(), Cop())
    z, provider = dem.elevations([45.0, 40.4], [5.7, -3.7])
    assert list(z) == [200.0, 650.0] and provider == "ign+copernicus"
    assert dem.elevations([45.0], [5.7])[1] == "ign"
    assert dem.elevations([40.4], [-3.7])[1] == "copernicus"
