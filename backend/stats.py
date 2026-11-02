"""Statistiques dérivées des activités Garmin.

Objectif : fournir beaucoup de statistiques sans recalculer les FIT à chaque
chargement de la page. Les statistiques qui nécessitent les points FIT sont
alimentées lors de la synchronisation et stockées dans activities.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
import math


def _dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T")[:19])


def _date(value):
    return _dt(value).date()


def _year_doy_month(start_time):
    d = _date(start_time)
    return d.year, d.timetuple().tm_yday, d.month


def yearly_cumulative(conn, metric="distance_m"):
    rows = conn.execute(f"SELECT start_time, {metric} FROM activities WHERE {metric} IS NOT NULL").fetchall()
    by_year_day = defaultdict(dict)
    for start_time, value in rows:
        if start_time and value is not None:
            year, doy, _ = _year_doy_month(start_time)
            by_year_day[year][doy] = by_year_day[year].get(doy, 0.0) + float(value)
    result = {}
    for year, day_values in by_year_day.items():
        cumulative, running = [], 0.0
        for doy in range(1, max(day_values) + 1):
            running += day_values.get(doy, 0.0)
            cumulative.append(round(running, 1))
        result[str(year)] = cumulative
    return result


def monthly_totals(conn, metric="distance_m"):
    rows = conn.execute(f"SELECT start_time, {metric} FROM activities WHERE {metric} IS NOT NULL").fetchall()
    by_year = defaultdict(lambda: [0.0] * 12)
    for start_time, value in rows:
        if start_time and value is not None:
            year, _, month = _year_doy_month(start_time)
            by_year[year][month - 1] += float(value)
    return {str(y): [round(v, 1) for v in months] for y, months in by_year.items()}


def _totals_between(conn, start_iso, end_iso):
    row = conn.execute(
        "SELECT COALESCE(SUM(distance_m),0), COALESCE(SUM(elevation_gain_m),0), "
        "COALESCE(SUM(duration_s),0), COUNT(*), COALESCE(SUM(hrss),0), COALESCE(SUM(trimp),0) "
        "FROM activities WHERE start_time >= ? AND start_time <= ?", (start_iso, end_iso)
    ).fetchone()
    return {"distance_km": round(row[0] / 1000, 1), "elevation_m": round(row[1]),
            "duration_h": round(row[2] / 3600, 1), "count": row[3],
            "hrss": round(row[4], 1), "trimp": round(row[5], 1)}


def _pct(current, previous):
    return None if previous in (None, 0) else round((current - previous) / previous * 100, 1)


def _record(row, divisor, unit):
    if not row:
        return None
    sport, value, start_time = row
    return {"sport": sport, "value": round(value / divisor, 1), "unit": unit,
            "date": str(start_time)[:10] if start_time else None}


def _safe_scalar(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _streaks(conn):
    days = [_date(r[0]) for r in conn.execute(
        "SELECT DISTINCT substr(start_time,1,10) FROM activities WHERE start_time IS NOT NULL ORDER BY 1"
    ).fetchall()]
    if not days:
        return {"active_days": 0, "longest_days": 0, "current_days": 0}
    longest = current = 1
    for a, b in zip(days, days[1:]):
        if b == a + timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    # current streak only if the last activity was today or yesterday
    current_streak = 0
    if days[-1] >= date.today() - timedelta(days=1):
        current_streak = 1
        for a, b in zip(reversed(days[:-1]), reversed(days[:-1])):
            break
        i = len(days) - 1
        while i > 0 and days[i] == days[i-1] + timedelta(days=1):
            current_streak += 1
            i -= 1
    return {"active_days": len(days), "longest_days": longest, "current_days": current_streak}


def _weekly_stats(conn):
    rows = conn.execute(
        "SELECT substr(start_time,1,10), distance_m, elevation_gain_m, duration_s, hrss "
        "FROM activities WHERE start_time IS NOT NULL"
    ).fetchall()
    weeks = defaultdict(lambda: {"distance": 0.0, "elevation": 0.0, "duration": 0.0, "hrss": 0.0, "count": 0})
    for d, dist, elev, dur, hrss in rows:
        day = date.fromisoformat(d)
        monday = day - timedelta(days=day.weekday())
        w = weeks[monday.isoformat()]
        w["distance"] += dist or 0
        w["elevation"] += elev or 0
        w["duration"] += dur or 0
        w["hrss"] += hrss or 0
        w["count"] += 1
    if not weeks:
        return {"highest_distance": None, "highest_elevation": None, "highest_hrss": None}
    def best(key):
        k, v = max(weeks.items(), key=lambda x: x[1][key])
        return {"week": k, "value": round(v[key] / (1000 if key == "distance" else 3600 if key == "duration" else 1), 1), "count": v["count"]}
    return {"highest_distance": best("distance"), "highest_elevation": best("elevation"), "highest_hrss": best("hrss")}


def _load_metrics(conn):
    today = date.today()
    end = today.isoformat() + "T23:59:59"
    d7 = (today - timedelta(days=6)).isoformat()
    d28 = (today - timedelta(days=27)).isoformat()
    d42 = (today - timedelta(days=41)).isoformat()
    t7 = _totals_between(conn, d7, end)
    t28 = _totals_between(conn, d28, end)
    t42 = _totals_between(conn, d42, end)
    # Monotony = moyenne quotidienne de charge / écart-type quotidien.
    rows = conn.execute(
        "SELECT substr(start_time,1,10), COALESCE(SUM(hrss),0) FROM activities "
        "WHERE start_time >= ? GROUP BY substr(start_time,1,10)", (d7,)
    ).fetchall()
    daily = {r[0]: r[1] for r in rows}
    vals = [daily.get((today - timedelta(days=i)).isoformat(), 0.0) for i in range(7)]
    mean = sum(vals) / 7
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / 7)
    monotony = round(mean / std, 2) if std else None
    return {"last_7_days": t7, "last_28_days": t28, "last_42_days": t42,
            "monotony_7d": monotony, "strain_7d": round(sum(vals) * monotony, 1) if monotony else None,
            "weekly_avg_hrss_28d": round(t28["hrss"] / 4, 1)}


def summary(conn):
    today = date.today()
    year_start = f"{today.year}-01-01"
    end_today = today.isoformat() + "T23:59:59"
    try:
        last_year_same_date = date(today.year - 1, today.month, today.day)
    except ValueError:
        last_year_same_date = date(today.year - 1, today.month, 28)
    ytd = _totals_between(conn, year_start, end_today)
    ytd_last = _totals_between(conn, f"{today.year-1}-01-01", last_year_same_date.isoformat()+"T23:59:59")
    month = _totals_between(conn, today.replace(day=1).isoformat(), end_today)
    alltime = _totals_between(conn, "0000-01-01", "9999-12-31T23:59:59")
    row = conn.execute("SELECT COUNT(DISTINCT substr(start_time,1,10)) FROM activities").fetchone()
    active_days = row[0] if row else 0
    avg = conn.execute(
        "SELECT AVG(distance_m), AVG(elevation_gain_m), AVG(duration_s), AVG(avg_hr), AVG(hrss), MAX(avg_hr), MAX(max_hr) FROM activities"
    ).fetchone()
    longest = conn.execute("SELECT sport,distance_m,start_time FROM activities WHERE distance_m IS NOT NULL ORDER BY distance_m DESC LIMIT 1").fetchone()
    climb = conn.execute("SELECT sport,elevation_gain_m,start_time FROM activities WHERE elevation_gain_m IS NOT NULL ORDER BY elevation_gain_m DESC LIMIT 1").fetchone()
    duration = conn.execute("SELECT sport,duration_s,start_time FROM activities WHERE duration_s IS NOT NULL ORDER BY duration_s DESC LIMIT 1").fetchone()
    hrss = conn.execute("SELECT sport,hrss,start_time FROM activities WHERE hrss IS NOT NULL ORDER BY hrss DESC LIMIT 1").fetchone()
    pace = conn.execute("SELECT sport, distance_m, duration_s, start_time FROM activities WHERE distance_m > 1000 AND duration_s > 0 ORDER BY duration_s/distance_m ASC LIMIT 1").fetchone()
    zone_row = conn.execute("SELECT COALESCE(SUM(hr_zone_1_s),0),COALESCE(SUM(hr_zone_2_s),0),COALESCE(SUM(hr_zone_3_s),0),COALESCE(SUM(hr_zone_4_s),0),COALESCE(SUM(hr_zone_5_s),0) FROM activities").fetchone()
    return {
        "all_time": alltime, "year_to_date": ytd, "year_to_date_last_year": ytd_last,
        "ytd_distance_change_pct": _pct(ytd["distance_km"], ytd_last["distance_km"]),
        "ytd_elevation_change_pct": _pct(ytd["elevation_m"], ytd_last["elevation_m"]),
        "this_month": month,
        "averages": {"distance_km": round((avg[0] or 0)/1000,1), "elevation_m": round(avg[1] or 0),
                      "duration_min": round((avg[2] or 0)/60,1), "avg_hr": round(avg[3] or 0,1),
                      "hrss": round(avg[4] or 0,1), "max_avg_hr": round(avg[5] or 0), "max_hr": round(avg[6] or 0)},
        "active_days": active_days,
        "streaks": _streaks(conn),
        "records": {
            "longest_distance": _record(longest,1000,"km"),
            "most_elevation": _record(climb,1,"m D+"),
            "longest_duration": _record(duration,3600,"h"),
            "highest_hrss": _record(hrss,1,"HRSS"),
            "fastest_activity": {"sport":pace[0],"pace_min_km":round(pace[2]/pace[1]*1000/60,2),"date":str(pace[3])[:10]} if pace else None,
        },
        "load": _load_metrics(conn),
        "weekly_records": _weekly_stats(conn),
        "heart_rate_zones": [round(x/60,1) for x in zone_row],
    }


def distributions(conn):
    weekday = [0] * 7
    hour = [0] * 24
    sports = defaultdict(lambda: {"count":0,"distance":0.0,"elevation":0.0,"duration":0.0,"hrss":0.0})
    rows = conn.execute("SELECT start_time,sport,distance_m,elevation_gain_m,duration_s,hrss FROM activities WHERE start_time IS NOT NULL").fetchall()
    for st, sport, dist, elev, dur, hrss in rows:
        d = _dt(st)
        weekday[d.weekday()] += 1
        hour[d.hour] += 1
        s = sports[sport or "unknown"]
        s["count"] += 1; s["distance"] += dist or 0; s["elevation"] += elev or 0; s["duration"] += dur or 0; s["hrss"] += hrss or 0
    return {
        "weekday": weekday, "hour": hour,
        "sports": {k: {"count":v["count"],"distance_km":round(v["distance"]/1000,1),"elevation_m":round(v["elevation"]),"duration_h":round(v["duration"]/3600,1),"hrss":round(v["hrss"],1)} for k,v in sorted(sports.items(), key=lambda x:x[1]["distance"], reverse=True)}
    }


def performance_series(conn, days=36500):
    """Série de performance lissée par mois.

    Les métriques par activité sont très bruitées (terrain, pente, météo,
    pauses, GPS...). Pour une courbe de tendance lisible, on agrège d'abord
    par mois avec une médiane, puis on applique une moyenne mobile centrée
    sur 5 mois. Les mois sans donnée restent des trous.
    """
    cutoff = (date.today() - timedelta(days=max(1, days))).isoformat()
    rows = conn.execute(
        "SELECT start_time, efficiency_factor, vam_mh, cardiac_drift_pct "
        "FROM activities WHERE start_time >= ? AND start_time IS NOT NULL "
        "ORDER BY start_time", (cutoff,)
    ).fetchall()

    monthly = defaultdict(lambda: {"efficiency": [], "vam": [], "drift": []})
    for st, ef, vam, drift in rows:
        key = str(st)[:7]  # YYYY-MM
        if ef is not None and ef > 0:
            monthly[key]["efficiency"].append(float(ef))
        if vam is not None and vam > 0:
            monthly[key]["vam"].append(float(vam))
        if drift is not None:
            monthly[key]["drift"].append(float(drift))

    def median(values):
        if not values:
            return None
        values = sorted(values)
        n = len(values)
        m = n // 2
        return values[m] if n % 2 else (values[m - 1] + values[m]) / 2

    # Crée tous les mois entre le premier et le dernier mois afin de ne pas
    # comprimer artificiellement l'axe temporel.
    keys = sorted(monthly)
    if not keys:
        return {"series": []}

    def next_month(y, m):
        return (y + (m == 12), 1 if m == 12 else m + 1)

    y, m = map(int, keys[0].split('-'))
    end_y, end_m = map(int, keys[-1].split('-'))
    all_keys = []
    while (y, m) <= (end_y, end_m):
        all_keys.append(f"{y:04d}-{m:02d}")
        y, m = next_month(y, m)

    raw = []
    for key in all_keys:
        vals = monthly[key]
        raw.append({
            "date": key + "-15",
            "month": key,
            "efficiency": median(vals["efficiency"]),
            "vam": median(vals["vam"]),
            "drift": median(vals["drift"]),
        })

    def smooth(field, radius=2):
        out = []
        for i, item in enumerate(raw):
            vals = []
            for j in range(max(0, i-radius), min(len(raw), i+radius+1)):
                v = raw[j][field]
                if v is not None:
                    vals.append(v)
            out.append(round(sum(vals) / len(vals), 4 if field == "efficiency" else 2) if vals else None)
        return out

    ef_s = smooth("efficiency")
    vam_s = smooth("vam")
    drift_s = smooth("drift")

    series = []
    for i, item in enumerate(raw):
        series.append({
            "date": item["date"],
            "month": item["month"],
            "efficiency": round(item["efficiency"], 4) if item["efficiency"] is not None else None,
            "vam": round(item["vam"], 1) if item["vam"] is not None else None,
            "drift": round(item["drift"], 2) if item["drift"] is not None else None,
            "efficiency_smooth": ef_s[i],
            "vam_smooth": vam_s[i],
            "drift_smooth": drift_s[i],
        })
    return {"series": series}

