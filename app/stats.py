"""
Calculs des pages de statistiques, à partir de la liste des sorties (queries.py).

Fonctions pures : elles reçoivent les sorties et la date du jour, pour être testables
et ne jamais dépendre de l'horloge.
"""
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


def home(acts, today: date) -> dict:
    last = acts[-1] if acts else None
    monday = today - timedelta(days=today.weekday())
    return {
        "ytd": year_to_date(acts, today),
        "all_time": totals(acts),
        "first_year": acts[0]["start"].year if acts else today.year,
        "last": last and {
            "name": last["name"], "date": last["start"].date().isoformat(),
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
    "pace": lambda a: a["pace_s_km"],
    "hr": lambda a: a["avg_hr"],
    "hrss": lambda a: a["hrss"],
}
PER_PAGE = 25


def pace_s_per_km(moving_s, distance_km):
    return moving_s / distance_km if moving_s and distance_km and distance_km > 0.2 else None


def activity_list(acts, year=None, terrain="all", sort="date", order="desc", page=1, query="") -> dict:
    """Sorties filtrées (année, terrain, texte dans le nom ou la description), triées et paginées."""
    rows = filter_terrain(acts, terrain)
    if year:
        rows = [a for a in rows if a["start"].year == year]
    q = query.strip().lower()
    if q:
        rows = [a for a in rows if q in (a["name"] or "").lower() or q in (a["description"] or "").lower()]
    for a in rows:
        a["pace_s_km"] = pace_s_per_km(a["moving_duration_s"], a["distance_km"])
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
            "moving_s": a["moving_duration_s"], "pace_s_km": a["pace_s_km"],
            "avg_hr": round(a["avg_hr"]) if a["avg_hr"] else None,
            "hrss": round(a["hrss"]) if a.get("hrss") is not None else None,
            "source": a["source"],
        } for a in chunk],
    }
