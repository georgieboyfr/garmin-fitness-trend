"""
Parcours similaires : regroupement des sorties qui suivent le même tracé (fonctions pures).

- Signature d'une trace : SIGNATURE_POINTS points répartis régulièrement le long de la
  distance parcourue. Deux sorties de même tracé, quelle que soit leur allure ou la
  densité d'enregistrement de la montre, ont des signatures point à point proches.
- Présélection : départs à moins de START_RADIUS_M et distances à ±DISTANCE_TOLERANCE.
- Écart de forme entre deux traces : pour chaque point de l'une, distance au point le plus
  proche de l'autre, en moyenne, dans les deux sens (le plus grand des deux). Insensible à
  un décalage le long du tracé (départ de montre un peu plus tôt). Sur les vraies données,
  un même parcours donne 10 à 30 m, une variante plus de 60 m.
- Sens : le même tracé parcouru dans l'autre sens est un parcours différent (comparaison
  point à point plus proche avec la trace inversée).
- Regroupement : chaque sortie rejoint le parcours dont la première sortie (sa référence)
  est la plus proche, si l'écart est sous MAX_TRACK_GAP_M, sinon elle ouvre un parcours.
"""
import numpy as np

from .elevation import EARTH_RADIUS_M, resample_positions

SIGNATURE_POINTS = 100
START_RADIUS_M = 300.0
DISTANCE_TOLERANCE = 0.05
MAX_TRACK_GAP_M = 40.0
MIN_DISTANCE_M = 1000.0


def signature(distance, lat, lon) -> np.ndarray | None:
    """(SIGNATURE_POINTS, 2) : latitudes et longitudes réparties le long de la trace."""
    d = np.asarray(distance, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    ok = np.isfinite(d) & np.isfinite(lat) & np.isfinite(lon)
    if ok.sum() < 2:
        return None
    total = np.nanmax(d[ok]) - np.nanmin(d[ok])
    if total < MIN_DISTANCE_M:
        return None
    grid, la, lo = resample_positions(d, lat, lon, total / (SIGNATURE_POINTS - 1))
    if la.size < SIGNATURE_POINTS:   # arrondi : on complète avec le dernier point
        la = np.append(la, [la[-1]] * (SIGNATURE_POINTS - la.size))
        lo = np.append(lo, [lo[-1]] * (SIGNATURE_POINTS - lo.size))
    return np.column_stack([la[:SIGNATURE_POINTS], lo[:SIGNATURE_POINTS]])


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _pointwise(sig_a, sig_b) -> float:
    return float(np.mean(haversine_m(sig_a[:, 0], sig_a[:, 1], sig_b[:, 0], sig_b[:, 1])))


def _nearest_mean(sig_a, sig_b) -> float:
    d = haversine_m(sig_a[:, 0][:, None], sig_a[:, 1][:, None],
                    sig_b[:, 0][None, :], sig_b[:, 1][None, :])
    return float(d.min(axis=1).mean())


def track_gap(sig_a, sig_b) -> float:
    """Écart de forme (m) entre deux signatures ; infini si elles sont parcourues en sens inverse."""
    if _pointwise(sig_a, sig_b) > 2 * _pointwise(sig_a, sig_b[::-1]):
        return float("inf")
    return max(_nearest_mean(sig_a, sig_b), _nearest_mean(sig_b, sig_a))


def comparable(a, b) -> bool:
    """Présélection : même départ et distance proche."""
    longest = max(a["distance_m"], b["distance_m"])
    if abs(a["distance_m"] - b["distance_m"]) > DISTANCE_TOLERANCE * longest:
        return False
    start_gap = haversine_m(a["sig"][0, 0], a["sig"][0, 1], b["sig"][0, 0], b["sig"][0, 1])
    return float(start_gap) <= START_RADIUS_M


def cluster(tracks, max_gap=MAX_TRACK_GAP_M) -> dict[int, int]:
    """tracks : dicts (id, distance_m, sig), du plus ancien au plus récent.
    Retourne {id de sortie: id de parcours} ; l'id d'un parcours est celui de sa première sortie."""
    refs = []              # sorties de référence (première sortie de chaque parcours)
    out = {}
    for t in tracks:
        best, best_gap = None, max_gap
        for r in refs:
            if comparable(t, r):
                gap = track_gap(t["sig"], r["sig"])
                if gap <= best_gap:
                    best, best_gap = r, gap
        if best is None:
            refs.append(t)
            out[t["id"]] = t["id"]
        else:
            out[t["id"]] = best["id"]
    return out
