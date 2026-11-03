"""
Calculs des pages de statistiques, à partir de la liste des sorties (queries.py).

Fonctions pures : elles reçoivent les sorties et la date du jour, pour être testables
et ne jamais dépendre de l'horloge.
"""
import math
from datetime import date, timedelta


def km_effort(distance_km: float, gain_m: float) -> float:
    """Convention ITRA : 100 m de D+ valent 1 km. Rend comparables route et trail."""
    return distance_km + gain_m / 100


def same_day_last_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:   # 29 février
        return day.replace(year=day.year - 1, day=28)


def totals(acts) -> dict:
    km = sum(a["distance_km"] for a in acts)
    gain = sum(a["gain_m"] for a in acts)
    return {
        "count": len(acts),
        "distance_km": round(km, 1),
        "gain_m": round(gain),
        "km_effort": round(km_effort(km, gain), 1),
        "hours": round(sum((a["moving_duration_s"] or a["duration_s"] or 0) for a in acts) / 3600, 1),
    }


def _pct(current, previous):
    return None if not previous else round((current - previous) / previous * 100, 1)


def year_to_date(acts, today: date) -> dict:
    """Cumul de l'année en cours face à l'année précédente à la même date."""
    last_day = same_day_last_year(today)
    cur = totals([a for a in acts if a["start"].year == today.year and a["start"].date() <= today])
    prev = totals([a for a in acts if a["start"].year == today.year - 1 and a["start"].date() <= last_day])
    return {
        "year": today.year,
        "current": cur,
        "previous": prev,
        "change_pct": {k: _pct(cur[k], prev[k]) for k in ("count", "distance_km", "gain_m", "km_effort")},
    }


def cumulative_by_day(acts, year: int, metric: str, until: date | None = None) -> list[float]:
    """Cumul jour par jour (index 0 = 1er janvier) d'une année, jusqu'à until inclus."""
    start = date(year, 1, 1)
    end = until or date(year, 12, 31)
    daily = [0.0] * ((end - start).days + 1)
    for a in acts:
        d = a["start"].date()
        if start <= d <= end:
            daily[(d - start).days] += a[metric]
    out, running = [], 0.0
    for v in daily:
        running += v
        out.append(round(running, 1))
    return out


def cumulative_all_years(acts, today: date, metric: str) -> dict[str, list[float]]:
    """Cumul jour par jour de chaque année (l'année en cours jusqu'à aujourd'hui)."""
    years = sorted({a["start"].year for a in acts} | {today.year})
    return {str(y): cumulative_by_day(acts, y, metric, until=today if y == today.year else None)
            for y in years}


def year_outlook(acts, today: date) -> dict:
    """Projection de fin d'année au rythme actuel et record annuel, pour chaque indicateur."""
    start = date(today.year, 1, 1)
    elapsed = (today - start).days + 1
    length = (date(today.year + 1, 1, 1) - start).days
    current = totals([a for a in acts if a["start"].year == today.year and a["start"].date() <= today])
    past = [r for r in yearly_table(acts) if r["year"] < today.year]
    out = {}
    for k in ("distance_km", "gain_m", "km_effort", "count"):
        best = max(past, key=lambda r: r[k], default=None)
        out[k] = {"projection": round(current[k] / elapsed * length) if elapsed >= 14 else None,
                  "record": best[k] if best else None, "record_year": best["year"] if best else None}
    out["per_week"] = round(current["count"] / (elapsed / 7), 1) if elapsed >= 7 else None
    return out


def home(acts, today: date) -> dict:
    last = acts[-1] if acts else None
    monday = today - timedelta(days=today.weekday())
    return {
        "ytd": year_to_date(acts, today),
        "outlook": year_outlook(acts, today),
        "all_time": totals(acts),
        "first_year": acts[0]["start"].year if acts else today.year,
        "last": last and {
            "id": last.get("id"), "name": last["name"], "date": last["start"].date().isoformat(),
            "distance_km": round(last["distance_km"], 2), "gain_m": round(last["gain_m"]),
            "moving_s": last["moving_duration_s"] or last["duration_s"],
        },
        "cumulative": cumulative_all_years(acts, today, "distance_km"),
        "week": totals([a for a in acts if monday <= a["start"].date() <= today]),
    }


# ---------- volume et régularité ----------

TERRAINS = {"all": "Toutes", "road": "Route", "trail": "Trail"}


def filter_terrain(acts, terrain: str):
    """Route : route et tapis ; trail : sorties au-delà de 20 m de D+ par km."""
    if terrain == "road":
        return [a for a in acts if a.get("terrain") in ("road", "indoor")]
    if terrain == "trail":
        return [a for a in acts if a.get("terrain") == "trail"]
    return acts


def _week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_streaks(weeks: set[date]) -> list[tuple[date, date, int]]:
    """Séries de semaines consécutives avec au moins une sortie : (premier lundi, dernier lundi, durée)."""
    out = []
    for w in sorted(weeks):
        if out and w - out[-1][1] == timedelta(weeks=1):
            out[-1] = (out[-1][0], w, out[-1][2] + 1)
        else:
            out.append((w, w, 1))
    return out


def regularity(acts, today: date) -> dict:
    weeks = {_week(a["start"].date()) for a in acts}
    streaks = week_streaks(weeks)
    longest = max(streaks, key=lambda s: s[2], default=None)
    this_week = _week(today)
    current = 0
    if streaks and streaks[-1][1] >= this_week - timedelta(weeks=1):
        current = streaks[-1][2]
    elapsed_weeks = (this_week - _week(date(today.year, 1, 1))).days // 7 + 1
    return {
        "active_weeks_this_year": len({_week(a["start"].date()) for a in acts
                                       if a["start"].year == today.year}),
        "elapsed_weeks_this_year": elapsed_weeks,
        "longest": longest and {"start": longest[0].isoformat(), "end": longest[1].isoformat(),
                                "weeks": longest[2]},
        "current_weeks": current,
    }


def yearly_table(acts) -> list[dict]:
    rows = []
    for y in sorted({a["start"].year for a in acts}):
        ya = [a for a in acts if a["start"].year == y]
        t = totals(ya)
        weeks = {_week(a["start"].date()) for a in ya}
        t.update({
            "year": y,
            "gain_per_km": round(t["gain_m"] / t["distance_km"], 1) if t["distance_km"] else 0,
            "active_weeks": len(weeks),
            "longest_streak": max((s[2] for s in week_streaks(weeks)), default=0),
            "hrss": round(sum(a.get("hrss") or 0 for a in ya)),
        })
        rows.append(t)
    return rows


def monthly(acts, metric: str) -> dict[str, list[float]]:
    out = {}
    for a in acts:
        months = out.setdefault(str(a["start"].year), [0.0] * 12)
        months[a["start"].month - 1] += a[metric]
    return {y: [round(v, 1) for v in m] for y, m in sorted(out.items())}


def daily_calendar(acts) -> dict[str, dict]:
    """Par jour : distance, D+ et noms des sorties (pour le calendrier en heatmap)."""
    days = {}
    for a in acts:
        d = days.setdefault(a["start"].date().isoformat(), {"km": 0.0, "gain": 0.0, "names": []})
        d["km"] = round(d["km"] + a["distance_km"], 2)
        d["gain"] = round(d["gain"] + a["gain_m"])
        d["names"].append(a["name"] or "")
    return days


def volume(acts, today: date) -> dict:
    for a in acts:
        a["km_effort"] = km_effort(a["distance_km"], a["gain_m"])
    return {
        "today": today.isoformat(),
        "years": sorted({a["start"].year for a in acts} | {today.year}),
        "cumulative": {m: cumulative_all_years(acts, today, m)
                       for m in ("distance_km", "gain_m", "km_effort")},
        "yearly": yearly_table(acts),
        "monthly": {m: monthly(acts, m) for m in ("distance_km", "gain_m")},
        "calendar": daily_calendar(acts),
        "regularity": regularity(acts, today),
        "all_time": totals(acts),
    }


# ---------- liste des sorties ----------

SORTS = {
    "date": lambda a: a["start"],
    "distance": lambda a: a["distance_km"],
    "gain": lambda a: a["gain_m"],
    "time": lambda a: a["moving_duration_s"],
    "elapsed": lambda a: a.get("elapsed_s"),
    "route": lambda a: a["route_cmp"]["diff_pct"] if a.get("route_cmp") else None,
    "pace": lambda a: a["pace_s_km"],
    "hr": lambda a: a["avg_hr"],
    "hrss": lambda a: a["hrss"],
}
PER_PAGE = 25


def pace_s_per_km(moving_s, distance_km):
    return moving_s / distance_km if moving_s and distance_km and distance_km > 0.2 else None


def route_comparison(acts) -> dict[int, dict]:
    """Pour chaque sortie d'un parcours couru plusieurs fois : écart (temps en mouvement) à la
    moyenne des autres passages, rang et record du parcours."""
    by_route = {}
    for a in acts:
        if a.get("route_id") is not None and a["moving_duration_s"]:
            by_route.setdefault(a["route_id"], []).append(a)
    out = {}
    for route_id, members in by_route.items():
        if len(members) < 2:
            continue
        times = sorted(m["moving_duration_s"] for m in members)
        total = sum(times)
        for m in members:
            t = m["moving_duration_s"]
            mean_others = (total - t) / (len(members) - 1)
            out[m["id"]] = {
                "route_id": route_id, "n": len(members), "mean_others_s": round(mean_others),
                "diff_s": round(t - mean_others), "diff_pct": round((t - mean_others) / mean_others * 100, 1),
                "rank": times.index(t) + 1, "best_s": times[0],
            }
    return out


def activity_list(acts, year=None, terrain="all", sort="date", order="desc", page=1, query="") -> dict:
    """Sorties filtrées (année, terrain, texte dans le nom ou la description), triées et paginées."""
    rows = filter_terrain(acts, terrain)
    if year:
        rows = [a for a in rows if a["start"].year == year]
    q = query.strip().lower()
    if q:
        rows = [a for a in rows if q in (a["name"] or "").lower() or q in (a["description"] or "").lower()]
    comparisons = route_comparison(acts)
    for a in rows:
        a["pace_s_km"] = pace_s_per_km(a["moving_duration_s"], a["distance_km"])
        a["route_cmp"] = comparisons.get(a["id"])
    sort = sort if sort in SORTS else "date"
    key = SORTS[sort]
    # les sorties sans valeur (pas de FC, pas de distance...) restent en fin de liste
    present = sorted((a for a in rows if key(a) is not None), key=key, reverse=(order != "asc"))
    rows = present + [a for a in rows if key(a) is None]
    pages = max(1, -(-len(rows) // PER_PAGE))
    page = min(max(1, page), pages)
    chunk = rows[(page - 1) * PER_PAGE: page * PER_PAGE]
    return {
        "total": len(rows),
        "totals": totals(rows),
        "page": page,
        "pages": pages,
        "rows": [{
            "id": a["id"], "date": a["start"].isoformat(timespec="minutes"), "name": a["name"],
            "description": a["description"], "terrain": a.get("terrain"),
            "distance_km": round(a["distance_km"], 2), "gain_m": round(a["gain_m"]),
            "moving_s": a["moving_duration_s"], "elapsed_s": a.get("elapsed_s"), "pace_s_km": a["pace_s_km"],
            "route": a["route_cmp"],
            "avg_hr": round(a["avg_hr"]) if a["avg_hr"] else None,
            "hrss": round(a["hrss"]) if a.get("hrss") is not None else None,
            "source": a["source"],
        } for a in chunk],
    }


# ---------- performance ----------

DISTANCE_LABELS = {1000: "1 km", 3000: "3 km", 5000: "5 km", 10000: "10 km", 21097.5: "Semi",
                   42195: "Marathon"}
DURATION_LABELS = {60: "1 min", 300: "5 min", 1200: "20 min", 3600: "1 h", 7200: "2 h"}
TOP = 10


def performance(efforts, terrain: str = "road", year: int | None = None) -> dict:
    """Records en fenêtre glissante (route ou trail), courbe allure-durée par année, VAM."""
    efforts = [e for e in efforts if e["terrain"] == terrain or (e["kind"] == "climb")]
    in_year = [e for e in efforts if year is None or e["year"] == year]
    years = sorted({e["year"] for e in efforts})

    records = []
    for key, label in DISTANCE_LABELS.items():
        rows = sorted((e for e in in_year
                       if e["kind"] == "distance" and e["key"] == key and e["terrain"] == terrain),
                      key=lambda e: e["value"])[:TOP]
        records.append({"key": key, "label": label, "top": [{
            "time_s": e["value"], "pace_s_km": e["value"] / (key / 1000), "date": e["date"],
            "name": e["name"], "description": e.get("description"), "activity_id": e["id"]} for e in rows]})

    # meilleur temps de chaque année pour chaque distance
    by_year = {}
    for e in efforts:
        if e["kind"] == "distance" and e["terrain"] == terrain:
            cell = by_year.setdefault(e["year"], {})
            if e["key"] not in cell or e["value"] < cell[e["key"]]:
                cell[e["key"]] = e["value"]

    # courbe allure-durée : meilleure allure tenue (s/km) sur chaque durée, par année
    curve = {}
    for e in efforts:
        if e["kind"] == "duration" and e["terrain"] == terrain and e["value"] > 0:
            pace = e["key"] / (e["value"] / 1000)
            cell = curve.setdefault(str(e["year"]), {})
            if e["key"] not in cell or pace < cell[e["key"]]:
                cell[e["key"]] = round(pace, 1)

    climbs = [e for e in efforts if e["kind"] == "climb"]
    vam_years = {}
    for e in climbs:
        if e["year"] not in vam_years or e["value"] > vam_years[e["year"]]["vam"]:
            vam_years[e["year"]] = {"vam": round(e["value"]), "gain": round(e["extra"] or 0),
                                    "date": e["date"], "name": e["name"], "id": e["id"]}
    top_climbs = sorted((e for e in climbs if year is None or e["year"] == year),
                        key=lambda e: -e["value"])[:TOP]

    return {
        "terrain": terrain, "year": year, "years": years,
        "records": records,
        "by_year": [{"year": y, "times": {str(k): by_year.get(y, {}).get(k) for k in DISTANCE_LABELS}}
                    for y in sorted(by_year, reverse=True)],
        "distance_labels": {str(k): v for k, v in DISTANCE_LABELS.items()},
        "curve": {y: [curve[y].get(k) for k in DURATION_LABELS] for y in sorted(curve)},
        "duration_labels": list(DURATION_LABELS.values()),
        "vam_by_year": [{"year": y, **vam_years[y]} for y in sorted(vam_years)],
        "top_climbs": [{"vam": round(e["value"]), "gain": round(e["extra"] or 0), "date": e["date"],
                        "name": e["name"], "description": e.get("description"), "id": e["id"]}
                       for e in top_climbs],
    }


# ---------- forme ----------

TAU_FITNESS = 42.0
TAU_FATIGUE = 7.0
# zones de forme (TSB), du plus frais au plus chargé
FORM_ZONES = [
    (25, "transition", "Très frais : la forme se perd"),
    (5, "fresh", "Frais : prêt pour une course"),
    (-10, "neutral", "Neutre : entretien"),
    (-30, "optimal", "Entraînement productif"),
    (float("-inf"), "overload", "Surcharge : risque de fatigue excessive"),
]
EASY_MAX_LTHR = 0.90        # sortie facile : FC moyenne sous la zone 3
FLAT_MAX_GAIN_PER_KM = 10.0
EF_MIN_MOVING_S = 1800


def form_zone(form: float) -> tuple[str, str]:
    for bound, key, label in FORM_ZONES:
        if form > bound:
            return key, label
    return FORM_ZONES[-1][1], FORM_ZONES[-1][2]


def banister(daily: dict, start: date, end: date) -> list[dict]:
    """Fitness (charge chronique, 42 j), fatigue (charge aiguë, 7 j) et forme (fitness − fatigue
    de la veille) jour par jour, à partir de la charge quotidienne (HRSS)."""
    k_fit = 1 - math.exp(-1 / TAU_FITNESS)
    k_fat = 1 - math.exp(-1 / TAU_FATIGUE)
    fitness = fatigue = 0.0
    out = []
    d = start
    while d <= end:
        stress = daily.get(d, 0.0)
        form = fitness - fatigue
        fitness += (stress - fitness) * k_fit
        fatigue += (stress - fatigue) * k_fat
        out.append({"date": d, "stress": stress, "fitness": fitness, "fatigue": fatigue, "form": form})
        d += timedelta(days=1)
    return out


def _median(values):
    v = sorted(values)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def is_easy_flat(a, lthr) -> bool:
    return (a.get("terrain") == "road" and (a["moving_duration_s"] or 0) >= EF_MIN_MOVING_S
            and a["distance_km"] > 0 and a["gain_m"] / a["distance_km"] < FLAT_MAX_GAIN_PER_KM
            and a["avg_hr"] is not None and a["avg_hr"] < EASY_MAX_LTHR * lthr and a.get("ef") is not None)


def _percentile(sorted_values, p):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def form_context(series, today: date, warmup_days=int(TAU_FITNESS)) -> dict:
    """Repères historiques de fitness, fatigue et forme pour situer la valeur du jour : extrêmes
    de tout l'historique, plage habituelle (25e–75e centile) des 12 derniers mois, valeur un an
    plus tôt et rang du jour parmi tous les jours. Les premières semaines (modèle qui démarre
    à zéro) sont exclues."""
    history = series[warmup_days:] if len(series) > warmup_days + 30 else series
    year_ago = same_day_last_year(today)
    last_year = [p for p in history if p["date"] > year_ago]
    by_date = {p["date"]: p for p in series}
    out = {}
    for key in ("fitness", "fatigue", "form"):
        values = sorted(p[key] for p in history)
        recent = sorted(p[key] for p in last_year)
        now = series[-1][key]
        top = max(history, key=lambda p: p[key])
        low = min(history, key=lambda p: p[key])
        out[key] = {
            "min": round(low[key], 1), "min_date": low["date"].isoformat(),
            "max": round(top[key], 1), "max_date": top["date"].isoformat(),
            "p25_12m": round(_percentile(recent, 0.25), 1) if recent else None,
            "p75_12m": round(_percentile(recent, 0.75), 1) if recent else None,
            "mean_12m": round(sum(recent) / len(recent), 1) if recent else None,
            "year_ago": round(by_date[year_ago][key], 1) if year_ago in by_date else None,
            "rank_pct": round(sum(v < now for v in values) / len(values) * 100) if values else None,
        }
    return out


def linear_trend(points, since: date | None = None) -> dict | None:
    """Droite des moindres carrés (date, valeur) : extrémités et évolution par an, en valeur et en %."""
    pts = [(date.fromisoformat(d), v) for d, v in points if since is None or date.fromisoformat(d) >= since]
    if len(pts) < 5:
        return None
    x0 = pts[0][0]
    xs = [(d - x0).days for d, _ in pts]
    ys = [v for _, v in pts]
    n = len(pts)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    start_v, end_v = my + slope * (xs[0] - mx), my + slope * (xs[-1] - mx)
    per_year = slope * 365.25
    return {"start": [pts[0][0].isoformat(), round(start_v, 3)],
            "end": [pts[-1][0].isoformat(), round(end_v, 3)],
            "per_year": round(per_year, 3), "per_year_pct": round(per_year / my * 100, 1) if my else None,
            "n": n}


def forme(acts, today: date, lthr: float) -> dict:
    daily = {}
    for a in acts:
        if a.get("hrss"):
            daily[a["start"].date()] = daily.get(a["start"].date(), 0.0) + a["hrss"]
    start = min(daily) if daily else today
    series = banister(daily, start, today)
    cur = series[-1]
    week_ago = series[-8] if len(series) >= 8 else series[0]
    zone, zone_label = form_zone(cur["form"])

    peaks = {}
    for p in series:
        y = p["date"].year
        if y not in peaks or p["fitness"] > peaks[y]["fitness"]:
            peaks[y] = {"year": y, "fitness": round(p["fitness"], 1), "date": p["date"].isoformat()}

    # Efficiency Factor des sorties faciles et plates, et sa médiane par mois
    ef_points = [{"date": a["start"].date().isoformat(), "ef": round(a["ef"], 3), "name": a["name"],
                  "id": a.get("id")}
                 for a in acts if is_easy_flat(a, lthr)]
    by_month = {}
    for p in ef_points:
        by_month.setdefault(p["date"][:7], []).append(p["ef"])
    # tous les mois entre le premier et le dernier, vides compris : la courbe s'interrompt sur les trous
    ef_monthly = []
    if by_month:
        y, m = map(int, min(by_month).split("-"))
        last = max(by_month)
        while f"{y:04d}-{m:02d}" <= last:
            v = by_month.get(f"{y:04d}-{m:02d}", [])
            ef_monthly.append({"month": f"{y:04d}-{m:02d}", "ef": round(_median(v), 3) if v else None,
                               "n": len(v)})
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    # découplage des sorties d'au moins une heure, sur le plat (sinon la pente fausse l'allure)
    decoupling = [{"date": a["start"].date().isoformat(), "pct": round(a["decoupling_pct"], 1),
                   "name": a["name"], "id": a.get("id"),
                   "hours": round((a["moving_duration_s"] or 0) / 3600, 1)}
                  for a in acts if a.get("decoupling_pct") is not None and a.get("terrain") == "road"
                  and a["distance_km"] > 0 and a["gain_m"] / a["distance_km"] < FLAT_MAX_GAIN_PER_KM]

    zones = {}
    for a in acts:
        z = zones.setdefault(a["start"].year, [0.0] * 5)
        for i in range(5):
            z[i] += a.get(f"zone{i + 1}_s") or 0.0
    zone_years = []
    for y in sorted(zones):
        total = sum(zones[y])
        if total > 0:
            zone_years.append({"year": y, "pct": [round(v / total * 100, 1) for v in zones[y]],
                               "hours": round(total / 3600)})

    return {
        "context": form_context(series, today),
        "today": {"fitness": round(cur["fitness"], 1), "fatigue": round(cur["fatigue"], 1),
                  "form": round(cur["form"], 1), "zone": zone, "zone_label": zone_label,
                  "ramp": round(cur["fitness"] - week_ago["fitness"], 1)},
        "series": {"dates": [p["date"].isoformat() for p in series],
                   "fitness": [round(p["fitness"], 1) for p in series],
                   "fatigue": [round(p["fatigue"], 1) for p in series],
                   "form": [round(p["form"], 1) for p in series],
                   "stress": [round(p["stress"]) for p in series]},
        "peaks": [peaks[y] for y in sorted(peaks)],
        "ef_points": ef_points, "ef_monthly": ef_monthly,
        "ef_trend": {"all": linear_trend([(p["date"], p["ef"]) for p in ef_points]),
                     "12m": linear_trend([(p["date"], p["ef"]) for p in ef_points],
                                         same_day_last_year(today))},
        "decoupling": decoupling,
        "zones": zone_years,
        "lthr": lthr,
    }
