from datetime import date, datetime, timedelta

import pytest

from app import coach_plan as cp

TODAY = date(2026, 11, 4)                 # mercredi


def avail(*days):
    """days : (jour, statut, minutes)."""
    by = {d: (s, m) for d, s, m in days}
    return [{"weekday": d, "status": by.get(d, ("non", None))[0], "max_min": by.get(d, ("non", None))[1],
             "usual_min": None} for d in range(7)]


def test_load_and_fitness_are_inverse():
    load = cp.weekly_load_for(20.0, 25.0)
    assert cp.fitness_after(20.0, load) == pytest.approx(25.0)
    assert cp.weekly_load_for(20.0, 20.0) == pytest.approx(140.0)          # maintien : 7 × fitness
    assert cp.weekly_load_for(30.0, 0.0) == 0.0


def test_skeleton_tapers_by_duration_and_counts_cycles_back_from_taper():
    short = cp.skeleton(TODAY, date(2027, 1, 31), 3000)     # 13 semaines (2 nov. au 25 janv.), < 1 h 30
    assert [w["kind"] for w in short][-1] == "course" and "affûtage" not in [w["kind"] for w in short]
    long = cp.skeleton(TODAY, date(2027, 1, 31), 4 * 3600)
    assert [w["kind"] for w in long][-2:] == ["affûtage", "course"]
    before = [w for w in long if w["kind"] in ("charge", "allégée")]
    assert before[-1]["kind"] == "charge" and before[-4]["kind"] == "allégée"   # 3 + 1 à rebours
    assert [w["phase"] for w in before][0] == "foncier" and before[-1]["phase"] == "spécifique"
    assert long[0]["monday"] == date(2026, 11, 2) and len(long) == 13
    tiny = cp.skeleton(TODAY, date(2026, 11, 25), 4 * 3600)               # 4 semaines
    assert [w["phase"] for w in tiny] == ["spécifique", "spécifique", "affûtage", "course"]


def test_chosen_days_take_yes_then_optional_up_to_the_weekly_cap():
    a = avail((0, "oui", 50), (1, "oui", 50), (3, "oui", 70), (5, "optionnel", 120), (6, "optionnel", 90))
    assert [d["weekday"] for d in cp.chosen_days(a, 4)] == [0, 1, 3, 5]      # l'optionnel le plus long
    assert [d["weekday"] for d in cp.chosen_days(a, None)] == [0, 1, 3, 5, 6]
    every = avail(*[(d, "oui", 60) for d in range(7)])
    assert len(cp.chosen_days(every, None)) == 6                           # un jour de repos


def run(day, hrss, minutes, hard_share):
    total = minutes * 60
    return {"start": datetime(day.year, day.month, day.day, 8), "hrss": hrss, "moving_duration_s": total,
            "zone1_s": total * (1 - hard_share), "zone2_s": 0, "zone3_s": total * hard_share,
            "zone4_s": 0, "zone5_s": 0}


def test_load_rates_are_learnt_from_easy_runs_and_sessions():
    acts = [run(TODAY - timedelta(days=i), 40, 60, 0.0) for i in range(1, 6)]
    acts += [run(TODAY - timedelta(days=i), 70, 60, 0.5) for i in range(10, 14)]
    r = cp.load_rates(acts, TODAY)
    assert r == {"easy": 40.0, "quality": 70.0, "personal": True, "easy_n": 5, "quality_n": 4}
    assert cp.load_rates([], TODAY)["easy"] == cp.DEFAULT_RATES[0]


RACE = {"name": "Trail", "race_date": "2027-01-31", "gpx_id": None, "distance_m": 30000, "gain_m": 1500,
        "duration_s": 4 * 3600, "target_text": None}
RATES = {"easy": 40.0, "quality": 60.0}


def week(kind="charge", phase="développement", monday=date(2026, 12, 7)):
    return {"kind": kind, "phase": phase, "monday": monday, "index": 1}


def test_week_puts_long_run_on_longest_day_and_never_two_hard_days_in_a_row():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 50), (2, "oui", 50), (3, "oui", 70),
                                (5, "oui", 150)), None)
    w = cp.build_week(week(), days, 300, RATES, RACE, {}, [], 170, 0)
    by = {s["weekday"]: s for s in w["sessions"]}
    assert by[5]["type"] == "sortie longue"
    hard = sorted(s["weekday"] for s in w["sessions"] if s["hard"])
    assert len(hard) == 2 and all(b - a > 1 for a, b in zip(hard, hard[1:], strict=False))
    assert all(abs(h - 5) > 1 for h in hard)                               # pas à côté de la sortie longue
    assert all(s["minutes"] <= next(d["max_min"] for d in days if d["weekday"] == s["weekday"])
               for s in w["sessions"])
    assert "FC sous 153 bpm" in by[5]["description"] and "m de D+" in by[5]["description"]


def test_hill_sessions_go_on_a_hilly_habit_day_flat_sessions_elsewhere():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 50), (3, "oui", 70), (5, "oui", 120)), 4)
    habit = [{"weekday": 0, "name": "Bastille", "hilly": True, "moving_min": 47}]
    fon = cp.build_week(week(phase="foncier"), days, 200, RATES, RACE, {}, habit, None, 0)
    q = next(s for s in fon["sessions"] if s["hard"])
    assert q["weekday"] == 0 and q["label"] == "Côtes courtes (Bastille)"
    dev = cp.build_week(week(phase="développement"), days, 200, RATES, RACE, {"threshold": 298}, habit,
                        None, 0)
    q = next(s for s in dev["sessions"] if s["hard"])
    assert q["weekday"] != 0 and q["type"] == "seuil" and "4:58 /km" in q["description"]
    assert next(s for s in dev["sessions"] if s["weekday"] == 0)["label"] == "Footing : Bastille"


def test_race_week_rests_the_day_before_and_keeps_a_short_reminder():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 50), (3, "oui", 70), (5, "oui", 120)), 4)
    race = {**RACE, "race_date": "2027-01-31"}                              # dimanche
    w = cp.build_week(week(kind="course", phase="course", monday=date(2027, 1, 25)), days, 80, RATES, race,
                      {}, [], None, 0)
    by = {s["weekday"]: s for s in w["sessions"]}
    assert by[6]["type"] == "course" and 5 not in by                       # veille au repos
    assert [s["type"] for s in w["sessions"] if s["type"] == "rappel"] == ["rappel"]


def test_plan_ramps_fitness_by_at_most_five_a_week_and_respects_the_peak_cap():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]   # fitness ≈ 30
    days = avail((0, "oui", 120), (1, "oui", 120), (3, "oui", 120), (5, "oui", 240), (6, "oui", 120))
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170)
    charge = [w for w in plan["weeks"] if w["kind"] == "charge"]
    fits = [plan["start_fitness"]] + [w["fitness_end"] for w in plan["weeks"]]
    assert all(b - a <= cp.RAMP_PER_WEEK + 0.6 for a, b in zip(fits, fits[1:], strict=False))
    assert max(fits) <= plan["cap_fitness"] + 0.6
    assert charge and not plan["capacity_limited"]
    light = [w for w in plan["weeks"] if w["kind"] == "allégée"]
    assert light and all(w["target_load"] < c["target_load"] for w in light for c in charge[:1])


def test_plan_flags_when_availability_limits_the_load():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 40), (3, "oui", 40))
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170)
    assert plan["capacity_limited"] and plan["capacity_min"] == 80
    assert cp.build_plan({**RACE, "race_date": "2026-10-01"}, TODAY, acts, days, None, [], {}, 170) is None
