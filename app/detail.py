"""
Fiche d'une sortie : résumé, tracé, profils (altitude, allure, FC) le long de la distance,
temps par kilomètre, meilleurs efforts et comparaison avec les autres passages du parcours.
"""
import numpy as np
import pyarrow.parquet as pq

from . import intervals
from .bests import CLIMB_GAINS_M, DISTANCES_M, DURATIONS_S, clean_distance
from .elevation import median_filter, resample, series_distance
from .elevation_job import dem_profile_path
from .metrics import _seconds
from .series import read_series
from .stats import (
    DISTANCE_LABELS,
    DURATION_LABELS,
    decoupling_applies,
    ef_reference,
    pace_s_per_km,
    route_comparison,
)

PROFILE_POINTS = 800        # points des profils et du tracé envoyés à la page
PACE_WINDOW_M = 200.0       # allure lissée sur 200 m


def _altitude(config, activity_id, table, source):
    """(distance, altitude) retenue pour le D+ : baromètre, ou profil MNT en cache."""
    if source == "barometer":
        alt = table.column("altitude_m").to_numpy(zero_copy_only=False).astype(float)
        return resample(series_distance(table), alt, 10.0)
    path = dem_profile_path(config, activity_id)
    if path.exists():
        prof = pq.read_table(path)
        return prof["distance_m"].to_numpy(), prof["altitude_m"].to_numpy().astype(float)
    return np.zeros(0), np.zeros(0)


def _round(values, digits):
    return [None if v is None or not np.isfinite(v) else round(float(v), digits) for v in values]


def session_intervals(fit_path, terrain, t, distance, hr) -> dict | None:
    """Intervalles de la séance : tours de la montre s'ils la décrivent, sinon détection sur
    l'allure (route seulement)."""
    rows = intervals.from_laps(intervals.read_laps(fit_path)) if fit_path and fit_path.exists() else None
    origin = "laps"
    if rows is None and terrain == "road":
        rows, origin = intervals.detect(t, distance, hr), "detected"
    if not rows:
        return None
    for r in rows:
        r["pace_s_km"] = r["duration_s"] / r["distance_m"] * 1000 if r["distance_m"] > 20 else None
    return {"origin": origin, "rows": rows, "summary": intervals.summary(rows)}


def profiles(config, activity_id, source, fit_path=None, terrain=None) -> dict:
    table = read_series(config.series_dir, activity_id,
                        ["timestamp", "distance_m", "lat", "lon", "altitude_m", "heart_rate"])
    t = _seconds(table.column("timestamp").to_numpy(zero_copy_only=False))
    raw_d = series_distance(table)
    lat = table.column("lat").to_numpy(zero_copy_only=False).astype(float)
    lon = table.column("lon").to_numpy(zero_copy_only=False).astype(float)
    hr = table.column("heart_rate").to_numpy(zero_copy_only=False).astype(float)
    tc, dc = clean_distance(t, raw_d)
    if dc.size < 2 or dc[-1] - dc[0] < 50:
        return {"km": [], "track": [], "splits": []}
    total = dc[-1] - dc[0]
    step = max(10.0, total / PROFILE_POINTS)
    grid = np.arange(dc[0], dc[-1] + 1e-9, step)
    keep = np.concatenate([[True], np.diff(dc) > 0])          # distance strictement croissante
    d_k, t_k = dc[keep], tc[keep]
    t_at = np.interp(grid, d_k, t_k)

    ok_hr = np.isfinite(hr) & (hr > 0) & np.isfinite(raw_d)
    hr_at = np.interp(grid, raw_d[ok_hr], hr[ok_hr]) if ok_hr.sum() > 1 else np.full(grid.size, np.nan)

    half = PACE_WINDOW_M / 2
    t_hi = np.interp(np.minimum(grid + half, d_k[-1]), d_k, t_k)
    t_lo = np.interp(np.maximum(grid - half, d_k[0]), d_k, t_k)
    span = np.minimum(grid + half, d_k[-1]) - np.maximum(grid - half, d_k[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        pace = np.where(span > 0, (t_hi - t_lo) / span * 1000, np.nan)
    pace = np.where((pace >= 120) & (pace <= 1200), pace, np.nan)   # 2'00" à 20'00" /km

    alt_d, alt = _altitude(config, activity_id, table, source)
    alt_at = (np.interp(grid, alt_d, median_filter(alt, 3), left=np.nan, right=np.nan)
              if alt.size > 1 else np.full(grid.size, np.nan))

    ok_pos = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(raw_d)
    track = []
    if ok_pos.sum() > 1:
        rd, rl, ro = raw_d[ok_pos], lat[ok_pos], lon[ok_pos]
        order = np.argsort(rd, kind="stable")
        track = np.column_stack([np.interp(grid, rd[order], rl[order]),
                                 np.interp(grid, rd[order], ro[order])]).round(6).tolist()

    # temps par kilomètre (dernier kilomètre partiel inclus)
    splits = []
    bounds = list(np.arange(dc[0], dc[-1], 1000.0)) + [dc[-1]]
    for k, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False), 1):
        if b - a < 100:
            continue
        ta, tb = np.interp([a, b], d_k, t_k)
        sel = (grid >= a) & (grid <= b)
        h = hr_at[sel]
        seg_alt = alt_at[sel]
        seg_alt = seg_alt[np.isfinite(seg_alt)]
        diffs = np.diff(seg_alt)
        splits.append({
            "km": k, "distance_m": round(b - a), "time_s": round(tb - ta),
            "pace_s_km": round((tb - ta) / (b - a) * 1000),
            "avg_hr": round(float(np.nanmean(h))) if np.isfinite(h).any() else None,
            "gain_m": round(float(diffs[diffs > 0].sum())) if diffs.size else None,
            "loss_m": round(float(-diffs[diffs < 0].sum())) if diffs.size else None,
        })
    return {
        "intervals": session_intervals(fit_path, terrain, t, raw_d, hr),
        "km": _round((grid - grid[0]) / 1000, 3),
        "time_s": _round(t_at - t_at[0], 0),
        "altitude": _round(alt_at, 1), "hr": _round(hr_at, 0), "pace": _round(pace, 0),
        "track": track, "splits": splits,
    }


def effort_ranks(efforts, activity_id, kind, key, terrain, year, higher_is_better=False) -> dict | None:
    """Rang d'un meilleur effort de la sortie parmi ceux de même nature : dans l'année et sur toute
    la période (même terrain, sauf pour la VAM, route et trail confondus)."""
    pool = [e for e in efforts if e["kind"] == kind and e["key"] == key
            and (kind == "climb" or e["terrain"] == terrain)]
    mine = next((e for e in pool if e["id"] == activity_id), None)
    if mine is None:
        return None

    def rank(rows):
        def beats(e):
            return e["value"] > mine["value"] if higher_is_better else e["value"] < mine["value"]

        better = sum(1 for e in rows if beats(e))
        return {"rank": better + 1, "of": len(rows)}

    return {"year": year, "in_year": rank([e for e in pool if e["year"] == year]), "all_time": rank(pool)}


def activity_detail(config, conn, activity_id: int, acts, efforts=None) -> dict | None:
    """acts : toutes les sorties de course (queries.running_activities), pour le parcours."""
    a = next((x for x in acts if x["id"] == activity_id), None)
    if a is None:
        return None
    m = conn.execute("SELECT * FROM activity_metrics WHERE activity_id=?", (activity_id,)).fetchone()
    e = conn.execute("SELECT * FROM activity_elevation WHERE activity_id=?", (activity_id,)).fetchone()
    s = conn.execute("SELECT * FROM activity_series WHERE activity_id=?", (activity_id,)).fetchone()
    model = conn.execute(
        "SELECT d.model FROM activities x JOIN devices d ON d.garmin_product = x.garmin_product WHERE x.id=?",
        (activity_id,)).fetchone()
    bests = conn.execute("SELECT kind, key, value, extra FROM activity_bests WHERE activity_id=?",
                         (activity_id,)).fetchall()

    cmp = route_comparison(acts).get(activity_id)
    passages = []
    if a.get("route_id") is not None:
        for x in acts:
            if x.get("route_id") == a["route_id"] and x["moving_duration_s"]:
                passages.append({"id": x["id"], "date": x["start"].date().isoformat(), "name": x["name"],
                                 "moving_s": x["moving_duration_s"], "avg_hr": x["avg_hr"],
                                 "pace_s_km": pace_s_per_km(x["moving_duration_s"], x["distance_km"])})

    zones = [m[f"zone{i}_s"] or 0 for i in range(1, 6)] if m else [0] * 5
    best = {(b["kind"], b["key"]): b["value"] for b in bests}
    year = a["start"].year

    def ranks(kind, key, higher=False):
        return effort_ranks(efforts or [], activity_id, kind, key, a.get("terrain"), year, higher)
    climb_gain = next((b["extra"] for b in bests if b["kind"] == "climb" and b["key"] == 0), None)
    return {
        "id": activity_id, "name": a["name"], "description": a["description"],
        "start": a["start"].isoformat(timespec="minutes"), "terrain": a.get("terrain"), "source": a["source"],
        "device": model[0] if model else None,
        "distance_km": round(a["distance_km"], 2), "gain_m": round(a["gain_m"]),
        "loss_m": round(e["loss_m"]) if e and e["loss_m"] is not None else None,
        "elevation_source": e["source"] if e else None,
        "moving_s": a["moving_duration_s"], "elapsed_s": a.get("elapsed_s"),
        "pace_s_km": pace_s_per_km(a["moving_duration_s"], a["distance_km"]),
        "avg_hr": round(a["avg_hr"]) if a["avg_hr"] else None,
        "max_hr": round(a["max_hr"]) if a["max_hr"] else None,
        "hrss": round(a["hrss"]) if a.get("hrss") is not None else None,
        "ef": round(m["ef"], 2) if m and m["ef"] else None,
        "ef_ref": ef_reference(acts, a),
        "decoupling_pct": round(a["decoupling_pct"], 1) if decoupling_applies(a) else None,
        "hrss_per_h": round(a["hrss"] / (a["moving_duration_s"] / 3600))
        if a.get("hrss") is not None and a["moving_duration_s"] else None,
        "zones_s": zones,
        "bests": {
            "distance": [{"label": DISTANCE_LABELS[k], "time_s": best[("distance", k)],
                          "ranks": ranks("distance", k)}
                         for k in DISTANCES_M if ("distance", k) in best],
            "duration": [{"label": DURATION_LABELS[k], "pace_s_km": k / (best[("duration", k)] / 1000)}
                         for k in DURATIONS_S if ("duration", k) in best],
            "climb": {"vam": round(best[("climb", 0)]), "gain": round(climb_gain or 0),
                      "ranks": ranks("climb", 0, higher=True)}
            if ("climb", 0) in best else None,
            "climb_steps": [{"gain": k, "vam": round(best[("climb", k)]),
                             "time_s": k / best[("climb", k)] * 3600, "ranks": ranks("climb", k, higher=True)}
                            for k in CLIMB_GAINS_M if ("climb", k) in best],
        },
        "route": cmp, "passages": passages,
        "profiles": profiles(config, activity_id, e["source"] if e else None,
                             config.fit_dir / f"{activity_id}.fit" if a["source"] == "garmin" else None,
                             a.get("terrain"))
        if s and s["status"] == "ok" else {"km": [], "track": [], "splits": []},
    }
