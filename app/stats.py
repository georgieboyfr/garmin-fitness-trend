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
