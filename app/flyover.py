"""
Survol 3D d'une sortie : trace rééchantillonnée régulièrement le long du terrain parcouru,
positions débarrassées du bruit GPS et cap de la caméra lissé.

Le cap de la caméra ne suit pas chaque virage : il est calculé sur la trace, déroulé (pas de saut
entre 359° et 0°) puis lissé sur quelques centaines de mètres. Une série de lacets se résume ainsi
à la direction générale de la montée, un demi-tour devient un virage progressif. Le navigateur se
contente d'interpoler ces valeurs et d'éviter que le relief ne cache le coureur (il connaît le
terrain affiché, pas le serveur).

Fonctions pures, testées ; rien n'est enregistré en base.
"""
import numpy as np

EARTH_RADIUS_M = 6_371_000.0
MAX_POINTS = 4000           # points envoyés au navigateur
MIN_STEP_M = 8.0            # pas minimal du rééchantillonnage
POS_SIGMA_M = 10.0          # lissage des positions (bruit GPS)
HEADING_SPAN_M = 40.0       # cap mesuré entre deux points distants de 40 m
HEADING_SIGMA_M = 160.0     # lissage du cap de la caméra
ALT_SIGMA_M = 25.0          # lissage de l'altitude avant la pente
PACE_WINDOW_M = 200.0       # allure lissée sur 200 m, comme sur le profil
MAX_GRADE_PCT = 45.0


def gaussian_smooth(values, sigma_samples: float) -> np.ndarray:
    """Moyenne glissante gaussienne, bords prolongés par la valeur extrême."""
    v = np.asarray(values, dtype=float)
    if sigma_samples <= 0 or v.size < 2:
        return v.copy()
    radius = max(1, int(round(3 * sigma_samples)))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma_samples) ** 2)
    kernel /= kernel.sum()
    return np.convolve(np.pad(v, radius, mode="edge"), kernel, mode="valid")


def local_xy(lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """Coordonnées planes en mètres (est, nord) autour du premier point : exactes à l'échelle
    d'une sortie."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    lat0 = np.radians(lat[0])
    x = np.radians(lon - lon[0]) * EARTH_RADIUS_M * np.cos(lat0)
    y = np.radians(lat - lat[0]) * EARTH_RADIUS_M
    return x, y


def headings_deg(x, y, span: int) -> np.ndarray:
    """Cap (degrés, 0 = nord, sens horaire) entre les points i − span/2 et i + span/2, déroulé :
    il varie continûment et peut dépasser 360° sur une boucle."""
    n = len(x)
    half = max(1, span // 2)
    idx = np.arange(n)
    a = np.clip(idx - half, 0, n - 1)
    b = np.clip(idx + half, 0, n - 1)
    dx, dy = x[b] - x[a], y[b] - y[a]
    raw = np.arctan2(dx, dy)
    # points immobiles (rares après le rééchantillonnage) : cap du point précédent
    still = np.hypot(dx, dy) < 1e-6
    if still.any() and not still.all():
        good = np.flatnonzero(~still)
        raw = raw[good[np.clip(np.searchsorted(good, idx, side="right") - 1, 0, good.size - 1)]]
    return np.degrees(np.unwrap(raw))


def _increasing(values) -> np.ndarray:
    """Suite rendue strictement croissante (pour np.interp)."""
    v = np.maximum.accumulate(np.asarray(values, dtype=float))
    return v + np.arange(v.size) * 1e-9


def flyover(t, lat, lon, distance, hr=None, alt_distance=None, alt=None) -> dict | None:
    """Trace du survol.

    t : secondes ; lat, lon : degrés ; distance : distance de la montre (m), pour les km affichés ;
    hr : FC ; alt_distance, alt : altitude retenue pour le D+ en fonction de la distance de la montre.
    Renvoie None sans trace GPS exploitable.
    """
    t = np.asarray(t, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    distance = np.asarray(distance, dtype=float)
    ok = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) > 1e-9)
    if ok.sum() < 2:
        return None
    order = np.argsort(t[ok], kind="stable")
    tt, la, lo = t[ok][order], lat[ok][order], lon[ok][order]
    x, y = local_xy(la, lo)
    # distance parcourue sur la trace, mesurée après un léger lissage (le bruit GPS l'allonge)
    x, y = gaussian_smooth(x, 2), gaussian_smooth(y, 2)
    geo = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    total = geo[-1]
    if total < 50:
        return None
    step = max(MIN_STEP_M, total / (MAX_POINTS - 1))
    grid = np.linspace(0.0, total, int(total // step) + 1)
    step = grid[1] - grid[0]
    g = _increasing(geo)

    # positions lissées, puis converties en degrés
    xs = gaussian_smooth(np.interp(grid, g, x), POS_SIGMA_M / step)
    ys = gaussian_smooth(np.interp(grid, g, y), POS_SIGMA_M / step)
    lat0 = np.radians(la[0])
    lat_s = la[0] + np.degrees(ys / EARTH_RADIUS_M)
    lon_s = lo[0] + np.degrees(xs / (EARTH_RADIUS_M * np.cos(lat0)))

    heading = gaussian_smooth(headings_deg(xs, ys, int(round(HEADING_SPAN_M / step))), HEADING_SIGMA_M / step)

    # temps écoulé et distance de la montre à chaque point
    time_s = np.interp(grid, g, tt)
    okd = np.isfinite(t) & np.isfinite(distance)
    if okd.sum() >= 2:
        o = np.argsort(t[okd], kind="stable")
        watch = np.maximum.accumulate(distance[okd][o])
        km_d = np.interp(time_s, _increasing(t[okd][o]), watch)
    else:
        km_d = grid.copy()
    start_d = km_d[0]             # distance de la montre au premier point GPS
    km_d = km_d - start_d

    # allure sur 200 m (distance de la montre), bornée comme sur le profil
    kd = _increasing(km_d)
    half = PACE_WINDOW_M / 2
    hi = np.minimum(km_d + half, km_d[-1])
    lo_ = np.maximum(km_d - half, 0.0)
    span = hi - lo_
    with np.errstate(divide="ignore", invalid="ignore"):
        dt = np.interp(hi, kd, time_s) - np.interp(lo_, kd, time_s)
        pace = np.where(span > 0, dt / span * 1000, np.nan)
    pace = np.where((pace >= 120) & (pace <= 1200), pace, np.nan)

    hr_at = np.full(grid.size, np.nan)
    if hr is not None:
        hr = np.asarray(hr, dtype=float)
        okh = np.isfinite(t) & np.isfinite(hr) & (hr > 0)
        if okh.sum() >= 2:
            o = np.argsort(t[okh], kind="stable")
            hr_at = np.interp(time_s, _increasing(t[okh][o]), hr[okh][o])

    alt_at = np.full(grid.size, np.nan)
    grade_pct = np.full(grid.size, np.nan)
    if alt is not None and alt_distance is not None and len(alt) > 1:
        ad, av = np.asarray(alt_distance, dtype=float), np.asarray(alt, dtype=float)
        oka = np.isfinite(ad) & np.isfinite(av)
        if oka.sum() >= 2:
            alt_at = np.interp(km_d + start_d, _increasing(ad[oka]), av[oka])
            smooth = gaussian_smooth(alt_at, ALT_SIGMA_M / step)
            grade_pct = np.clip(np.gradient(smooth, kd) * 100, -MAX_GRADE_PCT, MAX_GRADE_PCT)

    def rounded(values, digits):
        return [None if not np.isfinite(v) else round(float(v), digits) for v in values]

    return {
        "step_m": round(float(step), 2),
        "lat": np.round(lat_s, 6).tolist(), "lon": np.round(lon_s, 6).tolist(),
        "heading": np.round(heading, 1).tolist(),
        "km": np.round(km_d / 1000, 3).tolist(), "time_s": np.round(time_s - time_s[0]).tolist(),
        "pace": rounded(pace, 0), "hr": rounded(hr_at, 0),
        "alt": rounded(alt_at, 1), "grade": rounded(grade_pct, 1),
    }
