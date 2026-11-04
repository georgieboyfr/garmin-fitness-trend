from datetime import date, datetime, timedelta

import pytest

from app import coach_plan as cp

TODAY = date(2026, 11, 4)                 # mercredi


def text(session):
    """Tout ce qu'affiche une séance : description, étapes et leurs cibles."""
    steps = " ".join(f"{x['text']} {x['target']}" for x in session.get("steps", []))
    return f"{session['description']} {steps}"


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
    assert r == {"steady": 55.0, "quality_min": 60, "easy": 40.0, "quality": 70.0, "personal": True,
                 "easy_n": 5, "quality_n": 4,
                 "easy_pace": None, "easy_vam": cp.DEFAULT_EASY_VAM, "easy_vam_personal": False}
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
    assert "FC sous 153" in text(by[5]) and "m de D+" in text(by[5])


def test_hill_sessions_go_on_a_hilly_habit_day_flat_sessions_elsewhere():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 50), (3, "oui", 70), (5, "oui", 120)), 4)
    habit = [{"weekday": 0, "name": "Bastille", "hilly": True, "moving_min": 47}]
    fon = cp.build_week(week(phase="foncier"), days, 200, RATES, RACE, {}, habit, None, 0)
    q = next(s for s in fon["sessions"] if s["hard"])
    assert q["weekday"] == 0 and q["label"] == "Côtes courtes (Bastille)"
    dev = cp.build_week(week(phase="développement"), days, 200, RATES, RACE, {"threshold": 298}, habit,
                        None, 0)
    q = next(s for s in dev["sessions"] if s["hard"])
    assert q["weekday"] != 0 and q["type"] == "seuil" and "4:52 à 5:04 /km" in text(q)
    assert next(s for s in dev["sessions"] if s["weekday"] == 0)["label"] == "Footing vallonné : Bastille"


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


def test_trail_reminder_is_on_hills_and_road_reminder_at_race_pace():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 50), (3, "oui", 70), (5, "oui", 120)), 4)
    taper = week(kind="affûtage", phase="affûtage")
    trail = cp.build_week(taper, days, 100, RATES, RACE, {"race": None}, [], None, 0)
    q = next(s for s in trail["sessions"] if s["hard"])
    assert q["label"] == "Rappel en côte" and "/km" not in text(q)
    road_race = {**RACE, "gain_m": 50, "distance_m": 21100}
    road = cp.build_week(taper, days, 100, RATES, road_race, {"race": 300}, [], None, 0)
    q = next(s for s in road["sessions"] if s["hard"])
    assert q["label"] == "Rappel d'allure" and "4:57 à 5:03 /km" in text(q)


def test_taper_lowers_fitness_a_little_but_leaves_the_runner_fresh_on_race_day():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 120), (1, "oui", 120), (3, "oui", 120), (5, "oui", 240))
    plan = cp.build_plan({**RACE, "race_date": "2027-01-31"}, TODAY, acts, days, None, [], {}, 170)
    assert plan["race_fitness"] < plan["peak_fitness"]                  # l'affûtage coûte un peu de fitness
    assert plan["race_form"] > 0 and plan["race_form_pct"] > 5        # mais on arrive frais
    assert plan["race_form_zone"] in ("fresh", "transition") and "frais" in plan["race_form_label"].lower()
    assert plan["start_fitness"] > 0


def test_key_sessions_and_long_runs_vary_from_week_to_week():
    days = cp.chosen_days(avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 70), (5, "oui", 150)), 4)
    keys, longs = [], []
    for i in range(4):
        w = cp.build_week({**week(phase="spécifique"), "index": i + 1}, days, 220, RATES, RACE, {}, [],
                          170, i)
        keys.append(next(s["type"] for s in w["sessions"] if s["key"]))
        longs.append(next(s["label"] for s in w["sessions"] if s["type"] == "sortie longue"))
    assert all(a != b for a, b in zip(keys, keys[1:], strict=False)), keys
    assert len(set(longs)) >= 2, longs


def test_trail_long_run_climbs_at_the_runner_easy_rate_not_race_rate():
    days = cp.chosen_days(avail((1, "oui", 60), (5, "oui", 120)), 2)
    paces = {"easy_vam": 360}
    w = cp.build_week(week(phase="développement"), days, 120, RATES, RACE, paces, [], 170, 0)
    long = next(s for s in w["sessions"] if s["type"] == "sortie longue")
    hours = long["minutes"] / 60
    assert f"environ {round(360 * hours, -1):.0f} m de D+" in text(long)  # 360 m/h, pas 375 m/h (course)
    assert "marcher dans les montées" in text(long)


def test_plan_is_compared_with_carrying_on_as_before():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 120), (1, "oui", 120), (3, "oui", 120), (5, "oui", 240))
    plan = cp.build_plan({**RACE, "race_date": "2027-01-31"}, TODAY, acts, days, None, [], {}, 170)
    c = plan["continue"]
    assert c["weekly_load"] == pytest.approx(210, abs=15)             # 60 HRSS un jour sur deux
    assert plan["race_form"] > c["race_form"]                         # l'affûtage : plus frais que sans plan
    assert len(plan["series"]) == (date(2027, 1, 31) - date(2026, 11, 2)).days
    assert {"fitness", "form", "continue_fitness", "continue_form"} <= set(plan["series"][0])
    assert plan["hill_sessions"] >= 1 and plan["long_runs"] >= 10


def test_plan_never_starts_with_a_light_week_and_tapers_one_week_under_two_hours():
    weeks = cp.skeleton(TODAY, date(2026, 12, 13), 5938)                  # 6 semaines, course de 1 h 39
    assert [w["kind"] for w in weeks][:2] == ["charge", "charge"]
    assert [w["kind"] for w in weeks][-2:] == ["charge", "course"]       # une semaine d'affûtage
    long_race = cp.skeleton(TODAY, date(2026, 12, 13), 3 * 3600)
    assert [w["kind"] for w in long_race][-2:] == ["affûtage", "course"]


def test_long_runs_finish_steady_every_other_charge_week():
    days = cp.chosen_days(avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 70), (5, "oui", 150)), 4)
    labels = []
    for i in (1, 2):
        w = cp.build_week({**week(phase="foncier"), "index": i}, days, 220, RATES, RACE, {}, [], 170, 0)
        labels.append(next(s for s in w["sessions"] if s["type"] == "sortie longue"))
    assert "fin soutenue" not in labels[0]["label"] and "fin soutenue" in labels[1]["label"]
    finish = labels[1]["steps"][-1]
    assert finish["kind"] == "work" and "allure soutenue" in finish["text"]
    assert cp.session_load(labels[1], RATES) > labels[1]["minutes"] * RATES["easy"] / 60   # elle charge plus



def test_volume_ramps_by_the_runner_choice_from_the_current_load():
    acts = [run(TODAY - timedelta(days=i), 40, 60, 0.0) for i in range(1, 200, 3)]   # petite fitness
    days = avail((0, "oui", 120), (1, "oui", 120), (3, "oui", 120), (5, "oui", 240), (6, "oui", 120))
    race = {**RACE, "race_date": "2027-03-28"}
    for pct in (10, 15):
        plan = cp.build_plan(race, TODAY, acts, days, None, [], {}, 170, {"ramp_pct": pct})
        assert plan["options"]["ramp_pct"] == pct
        charge = [w["target_load"] for w in plan["weeks"] if w["kind"] == "charge"]
        start = cp.weekly_load_for(plan["start_fitness"], plan["start_fitness"])
        assert charge[0] <= start * (1 + pct / 100) + 1
        assert all(b <= a * (1 + pct / 100) + 1 for a, b in zip(charge, charge[1:], strict=False))
    slow = cp.build_plan(race, TODAY, acts, days, None, [], {}, 170, {"ramp_pct": 10})
    fast = cp.build_plan(race, TODAY, acts, days, None, [], {}, 170, {"ramp_pct": 15})
    assert fast["weeks"][2]["target_load"] > slow["weeks"][2]["target_load"]


def test_long_runs_extend_every_other_charge_week_toward_race_duration():
    weeks = cp.skeleton(TODAY, date(2027, 5, 22), 3 * 3600)
    days = cp.chosen_days(avail((1, "oui", 60), (3, "oui", 60), (5, "oui", 120)), 3)
    ext = cp.long_extensions(weeks, days, {"duration_s": 3 * 3600}, True)
    late = [w["index"] for w in weeks
            if w["phase"] in ("développement", "spécifique") and w["kind"] == "charge"]
    spec = [w["index"] for w in weeks if w["phase"] == "spécifique" and w["kind"] == "charge"]
    assert ext and set(ext) <= set(late) and max(ext) == late[-1]         # la dernière avant l'affûtage
    assert set(ext.values()) == {160}                                      # 90 % de 3 h ; la progression dose
    assert all(b - a >= 2 for a, b in zip(sorted(ext), sorted(ext)[1:], strict=False))   # une sur deux
    assert cp.long_extensions(weeks, days, {"duration_s": 3 * 3600}, False) == {}
    assert cp.long_extensions(weeks, days, {"duration_s": 7200}, True) == {}      # 108 min < 120
    assert cp.long_extensions(weeks, days, {"duration_s": 6 * 3600}, True)[spec[-1]] == 180   # 3 h au plus
    assert cp._long_step(60) == pytest.approx(66) and cp._long_step(150) == pytest.approx(165)   # +10 %
    w = cp.build_week({**week(phase="spécifique"), "index": spec[-1]}, days, 260, RATES, RACE, {}, [], 170, 0,
                      160)
    long = next(s for s in w["sessions"] if s["type"] == "sortie longue")
    assert long["minutes"] == 160 and long.get("extended") and "à caler" in long["description"]


def test_weekly_gain_is_summed_and_targets_race_gain_in_specific_trail_weeks():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170)
    spec = [w for w in plan["weeks"] if w["phase"] == "spécifique"]
    assert spec and all(w["gain_target"] == 1500 for w in spec)
    assert all("gain_target" not in w for w in plan["weeks"] if w["phase"] == "foncier")
    for w in plan["weeks"]:
        total = sum(s.get("gain_m") or 0 for s in w["sessions"] if s["type"] != "course")
        assert w["gain_m"] == round(total, -1)
    footings = [s for w in spec if w["kind"] == "charge" for s in w["sessions"]
                if s["type"].startswith("footing")]
    assert footings and all(s["type"] == "footing vallonné" for s in footings)   # tous vallonnés


def test_race_week_reminder_three_or_four_days_before_never_the_day_before_yesterday_if_avoidable():
    race = {**RACE, "race_date": "2027-01-30"}                              # samedi
    wk = week(kind="course", phase="course", monday=date(2027, 1, 25))
    for open_days, expected in (((0, 1, 2, 3), 2), ((0, 1, 3), 1)):
        days = cp.chosen_days(avail(*[(d, "oui", 60) for d in open_days]), 4)
        w = cp.build_week(wk, days, 80, RATES, race, {}, [], None, 0)
        assert next(s["weekday"] for s in w["sessions"] if s["type"] == "rappel") == expected


def side_race(day, priority, km=20, gain=800, minutes=120, id_=9):
    return {"id": id_, "name": f"Course {priority}", "race_date": day.isoformat(), "priority": priority,
            "distance_m": km * 1000, "gain_m": gain, "duration_s": minutes * 60, "target_text": None}


def test_recovery_grows_with_effort_and_is_halved_for_a_c_race():
    assert cp.effort_km({"distance_m": 24000, "gain_m": 1400}) == pytest.approx(38)
    assert cp.recovery_days({"distance_m": 24000, "gain_m": 1400, "priority": "B"}) == 13
    assert cp.recovery_days({"distance_m": 24000, "gain_m": 1400, "priority": "C"}) == 6
    assert cp.recovery_days({"distance_m": 5000, "gain_m": 0, "priority": "B"}) == 2          # au moins 2
    assert cp.recovery_days({"distance_m": 160000, "gain_m": 10000, "priority": "B"}) == 21   # au plus 21
    assert cp.recovery_days({"duration_s": 3600, "priority": "B"}) == 3          # 10 km à 6 min/km


def test_b_race_gets_a_mini_taper_rest_the_day_before_and_a_recovery_after():
    days = cp.chosen_days(avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150)), 4)
    race_day = date(2026, 12, 13)                                       # dimanche
    cal = cp.race_calendar([side_race(race_day, "B")], date(2026, 11, 2), date(2027, 5, 22))
    assert race_day - timedelta(days=1) in cal["rest"]
    assert {race_day - timedelta(days=k) for k in (2, 3)} <= cal["easy"]
    assert len(cal["recovery"]) == cp.recovery_days(side_race(race_day, "B"))
    w = cp.build_week(week(phase="développement", monday=date(2026, 12, 7)), days, 120, RATES, RACE, {}, [],
                      170, 0, None, cal)
    by = {s["weekday"]: s for s in w["sessions"]}
    assert by[6]["type"] == "course" and by[6]["priority"] == "B" and not by[6]["main"]
    assert 5 not in by                                                  # veille au repos
    assert all(not s["hard"] for d, s in by.items() if d in (3, 4))     # mini-affûtage
    assert sum(1 for s in w["sessions"] if s["hard"] and s["type"] != "course") <= 1
    assert w["planned_load"] > 120                                      # la course s'ajoute
    after = cp.build_week(week(phase="développement", monday=date(2026, 12, 14)), days, 120, RATES, RACE, {},
                          [], 170, 0, None, cal)
    assert not any(s["hard"] or s["type"] == "sortie longue" for s in after["sessions"])   # récupération


def test_c_race_replaces_the_key_session_and_the_long_run():
    days = cp.chosen_days(avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150)), 4)
    c = side_race(date(2026, 12, 12), "C", minutes=90)
    cal = cp.race_calendar([c], date(2026, 11, 2), date(2027, 5, 22))
    w = cp.build_week(week(phase="développement", monday=date(2026, 12, 7)), days, 150, RATES, RACE, {}, [],
                      170, 0, None, cal)
    assert [s["type"] for s in w["sessions"] if s["hard"]] == ["course"]
    assert not any(s["type"] == "sortie longue" for s in w["sessions"])
    assert next(s for s in w["sessions"] if s["type"] == "course")["key"]


def test_plan_counts_side_races_and_shows_their_recovery():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    b = side_race(date(2026, 11, 29), "B")
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170, None, [b])
    race_week = next(w for w in plan["weeks"] if w["monday"] == "2026-11-23")
    assert any(s["type"] == "course" and not s["main"] for s in race_week["sessions"])
    nxt = next(w for w in plan["weeks"] if w["monday"] == "2026-11-30")
    assert nxt["events"] and nxt["events"][0]["name"] == "Course B" and not race_week["events"]
    alone = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170)
    assert nxt["target_load"] < next(w for w in alone["weeks"] if w["monday"] == "2026-11-30")["target_load"]
    past = side_race(TODAY - timedelta(days=3), "B")          # course passée : récupération en cours
    after = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170, None,
                          [past])
    assert after["weeks"][0]["events"]


def test_conflicts_offer_solutions_to_choose_from():
    a1 = {"id": 1, "name": "A1", "race_date": "2027-03-01", "priority": "A"}
    a2 = {"id": 2, "name": "A2", "race_date": "2027-04-01", "priority": "A"}
    b = {"id": 3, "name": "B1", "race_date": "2027-02-20", "priority": "B"}
    c = {"id": 4, "name": "C1", "race_date": "2027-02-26", "priority": "C"}
    found = cp.conflicts([b, c, a1, a2])
    assert len(found) == 3
    two_a = next(x for x in found if "deux courses A" in x["text"])
    assert {(s["race_id"], s["priority"]) for s in two_a["solutions"]} == {(1, "B"), (2, "B")}
    assert next(x for x in found if "B1" in x["text"])["solutions"][0]["priority"] == "C"
    assert next(x for x in found if "C1" in x["text"])["solutions"][0]["delete"]
    assert cp.conflicts([{**b, "race_date": "2027-01-10"}, a1]) == []


def test_optional_days_get_a_bonus_outside_the_plan():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 50), (3, "oui", 70), (5, "optionnel", 120)), 4)
    w = cp.build_week(week(phase="foncier"), days, 120, RATES, RACE, {}, [], 170, 0)
    by = {s["weekday"]: s for s in w["sessions"]}
    assert by[5]["optional"] and "(optionnelle)" in by[5]["label"] and not by[5]["key"]
    assert by[3]["type"] == "sortie longue" and not by[3].get("optional")   # le plan tient sur les jours oui
    assert w["minutes"] == sum(s["minutes"] for s in w["sessions"] if not s.get("optional"))
    ext = cp.build_week(week(phase="spécifique"), days, 120, RATES, RACE, {}, [], 170, 0, 160)
    bonus = next(s for s in ext["sessions"] if s.get("optional"))
    assert bonus["minutes"] == 160 and bonus["extended"]                    # l'allongée, le weekend
    assert next(s for s in ext["sessions"] if s["type"] == "sortie longue" and not s.get("optional"))[
        "minutes"] <= 70
    only = cp.chosen_days(avail((5, "optionnel", 120), (6, "optionnel", 90)), None)
    w2 = cp.build_week(week(phase="foncier"), only, 120, RATES, RACE, {}, [], 170, 0)
    assert not any(s.get("optional") for s in w2["sessions"])        # que des optionnels : le plan


def test_an_optional_day_once_every_three_weeks_enters_the_plan_those_weeks():
    a = avail((0, "oui", 50), (1, "oui", 60), (3, "oui", 80), (5, "optionnel", 120))
    a[5]["every"] = 3
    days = cp.chosen_days(a, 4)
    assert [d["weekday"] for d in cp.week_days(days, 3)] == [0, 1, 3, 5]
    assert cp.week_days(days, 3)[-1]["status"] == "oui"
    assert [d["weekday"] for d in cp.week_days(days, 4)] == [0, 1, 3]
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    plan = cp.build_plan({**RACE, "race_date": "2027-05-22", "duration_s": 3 * 3600}, TODAY, acts, a, 4, [],
                         {}, 170)
    by_index = {w["index"]: w for w in plan["weeks"]}
    sat = [i for i, w in by_index.items()
           if any(s["weekday"] == 5 and s["type"] != "course" for s in w["sessions"])]
    assert sat and all(i % 3 == 0 for i in sat)
    assert not any(s.get("optional") for w in plan["weeks"] for s in w["sessions"])     # compté, pas en bonus
    longest = max((s for w in plan["weeks"] for s in w["sessions"] if s["type"] == "sortie longue"),
                  key=lambda s: s["minutes"])
    assert longest["weekday"] == 5                                   # la plus longue tombe un weekend libre
    assert plan["capacity_min"] == 190 + 40


def test_rising_periods_learn_what_raised_the_runner_fitness():
    acts = []
    for block in range(3):                              # 3 blocs de 8 semaines qui montent, séparés de repos
        start = date(2024, 1, 1) + timedelta(weeks=20 * block)
        for i in range(0, 56, 2):
            hard = 0.5 if i % 6 == 0 else 0.15 if i % 6 == 2 else 0.0
            acts.append({**run(start + timedelta(days=i), 60 if hard else 40, 60, hard), "id": len(acts)})
    acts.append({**run(date(2024, 2, 1), 400, 300, 0.0), "id": 999})          # sortie exceptionnelle
    h = cp.rising_periods(acts, date(2025, 6, 1))
    assert h and h["periods"] >= 2
    assert h["runs_per_week"] == pytest.approx(3.5, abs=0.3) and h["weekly_min"] == pytest.approx(210, abs=20)
    assert h["count_share"]["hard"] == pytest.approx(1 / 3, abs=0.05)
    assert h["count_share"]["steady"] == pytest.approx(1 / 3, abs=0.05)
    assert sum(h["time_share"].values()) == pytest.approx(1, abs=0.01)
    assert cp.rising_periods(acts[:10], date(2025, 6, 1)) is None              # trop peu d'historique


def test_steady_runs_spread_over_weeks_and_quality_sessions_fill_the_day():
    assert [cp._spread(i, 0.5) for i in range(1, 7)] == [0, 1, 0, 1, 0, 1]
    days = cp.chosen_days(avail((0, "oui", 90), (1, "oui", 90), (3, "oui", 100)), 3)
    rates = {**RATES, "steady": 50.0, "quality_min": 70}
    w = cp.build_week(week(phase="développement"), days, 150, rates, RACE, {}, [], 170, 0, None, None, 1)
    steady = [s for s in w["sessions"] if s["type"] == "footing soutenu"]
    assert len(steady) == 1 and any(x["kind"] == "work" for x in steady[0]["steps"])
    assert cp.session_load(steady[0], rates) > steady[0]["minutes"] * rates["easy"] / 60
    q = next(s for s in w["sessions"] if s["hard"])
    assert q["steps"][-1]["text"].startswith("puis") and q["minutes"] <= 70     # durée de ses séances


def test_periods_replace_the_usual_days_with_the_planned_sessions():
    a = avail((0, "oui", 50), (1, "oui", 60), (3, "oui", 80), (5, "optionnel", 120))
    days = cp.chosen_days(a, 4)
    mon = date(2026, 12, 21)
    holiday = [{"kind": "vacances", "start": "2026-12-19", "end": "2027-01-03", "sessions": 5, "max_min": 90}]
    wd = cp.period_days(days, mon, holiday, a)
    assert len(wd) == 5 and all(d["max_min"] == 90 for d in wd)
    assert sum(1 for x, y in zip(wd, wd[1:], strict=False) if y["weekday"] - x["weekday"] == 1) <= 3
    sick = [{"kind": "maladie", "start": "2026-12-21", "end": "2026-12-27", "sessions": None}]
    assert cp.period_days(days, mon, sick, a) == []
    half = [{"kind": "deplacement", "start": "2026-12-24", "end": "2026-12-27", "sessions": 2}]
    wd = cp.period_days(days, mon, half, a)
    assert [d["weekday"] for d in wd if d.get("period")] == [5]                 # 2 × 4/7 : une séance
    assert [d["weekday"] for d in wd if not d.get("period")] == [0, 1]          # lundi et mardi gardés


def test_plan_follows_periods_with_a_reprise_after_illness():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    race = {**RACE, "race_date": "2027-03-28"}
    sick = {"kind": "maladie", "start": "2026-11-30", "end": "2026-12-06", "sessions": None}
    plan = cp.build_plan(race, TODAY, acts, days, None, [], {}, 170, {"periods": [sick]})
    alone = cp.build_plan(race, TODAY, acts, days, None, [], {}, 170)
    by = {w["monday"]: w for w in plan["weeks"]}
    ref = {w["monday"]: w for w in alone["weeks"]}
    assert by["2026-11-30"]["sessions"] == [] and by["2026-11-30"]["periods"][0]["kind"] == "maladie"
    assert by["2026-12-07"]["periods"][0]["kind"] == "reprise"
    assert by["2026-12-07"]["target_load"] < ref["2026-12-07"]["target_load"]
    assert plan["race_fitness"] < alone["race_fitness"]


def test_readiness_compares_recent_weeks_plan_and_race():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28", "duration_s": 3 * 3600}, TODAY, acts, days, None,
                         [], {}, 170)
    by = {r["key"]: r for r in plan["readiness"]}
    assert {"long", "gain", "longs", "hard", "regular"} <= set(by)
    assert by["long"]["need"] == 162 and by["gain"]["need"] == 1500
    assert by["long"]["now"] == 90 and by["long"]["plan"] > 90
    assert plan["continue"]["weeks"] == min(52, max(12, len(plan["weeks"])))


def test_day_after_a_race_is_a_rest_day():
    cal = cp.race_calendar([side_race(date(2026, 12, 13), "B")], date(2026, 11, 2), date(2027, 5, 22))
    assert date(2026, 12, 14) in cal["rest"]
    short_c = cp.race_calendar([side_race(date(2026, 12, 13), "C", minutes=40)], date(2026, 11, 2),
                               date(2027, 5, 22))
    assert date(2026, 12, 14) not in short_c["rest"]


def test_load_spikes_catch_a_block_of_big_days_not_a_single_long_run():
    acts = []
    for w in range(30):                                   # 30 semaines de 120 à 210 de charge
        for k in (0, 2, 4):
            acts.append({**run(date(2026, 1, 5) + timedelta(weeks=w, days=k), 40 + 10 * (w % 4), 60, 0.0),
                         "id": len(acts)})
    long_one = date(2026, 1, 5) + timedelta(weeks=20, days=6)
    acts.append({**run(long_one, 90, 180, 0.0), "id": 900})             # une longue sortie isolée
    block = date(2026, 1, 5) + timedelta(weeks=25)
    acts += [{**run(block + timedelta(days=k), 200, 220, 0.0), "id": 901 + k} for k in (4, 5, 6)]
    spikes = cp.load_spikes(acts, date(2026, 9, 1))
    assert set(spikes) == {block} and 0 < spikes[block] < 1
    assert cp.monday(long_one) not in spikes
    daily = cp.smoothed_daily(acts, date(2026, 9, 1))
    week = sum(v for d, v in daily.items() if cp.monday(d) == block)
    raw = sum(a["hrss"] for a in acts if cp.monday(a["start"].date()) == block)
    assert week == pytest.approx(raw * spikes[block])                  # ramenée à la borne
    assert all(cp.monday(a["start"].date()) != block for a in cp.ordinary(acts, date(2026, 9, 1)))


def test_long_run_progresses_by_the_usual_step():
    acts = [run(TODAY - timedelta(days=i), 60, 60, 0.0) for i in range(1, 200, 2)]    # sorties d'une heure
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 240))
    plan = cp.build_plan({**RACE, "race_date": "2027-05-22", "duration_s": 4 * 3600}, TODAY, acts, days,
                         None, [], {}, 170)
    hist = [60]
    for w in plan["weeks"]:
        longs = [s.get("level_min", s["minutes"]) for s in w["sessions"] if s["type"] == "sortie longue"]
        if longs:
            assert max(longs) <= cp._long_step(max(hist[-4:])) + 0.01
        hist.append(max(longs, default=0))
    assert max(hist) > 120                                           # elle monte au fil du plan


def test_taper_keeps_frequency_and_strength_is_advised():
    days = cp.chosen_days(avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 120)), 4)
    w = cp.build_week(week(kind="affûtage", phase="affûtage"), days, 120, RATES, RACE, {}, [], 170, 0)
    assert len(w["sessions"]) == 4                     # footings courts plutôt qu'un jour de moins
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    a = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, a, None, [], {}, 170)
    by = {w["phase"]: w["strength"] for w in plan["weeks"] if w["kind"] == "charge"}
    assert by["foncier"] == 2 and by["spécifique"] == 1
    assert plan["weeks"][-1]["strength"] == 0                        # rien en semaine de course


def test_key_sessions_make_a_full_round_before_repeating():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 70), (5, "oui", 150))
    plan = cp.build_plan({**RACE, "race_date": "2027-05-22"}, TODAY, acts, days, None, [], {}, 170)
    for phase in ("foncier", "développement", "spécifique"):
        types = [x["type"] for w in plan["weeks"] if w["phase"] == phase and w["kind"] == "charge"
                 for x in w["sessions"] if x["hard"] and x["type"] != "course"]
        catalog = len(cp.wk.QUALITY[(phase, True)])
        head = types[:catalog]
        assert len(set(head)) == len(head), (phase, types)          # aucune répétition avant un tour complet
    flat = {"fartlek", "vma", "pyramide", "seuil", "tempo"}
    assert any(t in flat for w in plan["weeks"] for t in (x["type"] for x in w["sessions"]))   # du plat aussi


# ---------- maintien de forme (étape 7) ----------

def steady_runner(until, weeks=30, hrss=50, minutes=60, gap=None):
    """Quatre sorties par semaine (lundi, mardi, jeudi, samedi plus long), sauf pendant gap (début, fin)."""
    acts = []
    start = cp.monday(until) - timedelta(weeks=weeks)
    for w in range(weeks):
        for k, mult in ((0, 1.0), (1, 1.0), (3, 1.0), (5, 1.5)):
            d = start + timedelta(weeks=w, days=k)
            if d >= until or (gap and gap[0] <= d <= gap[1]):
                continue
            acts.append({**run(d, hrss * mult, minutes * mult, 0.15 if k == 1 else 0.0), "id": len(acts),
                         "terrain": "road", "distance_km": 10 * mult, "gain_m": 50})
    return acts


MAINT_DAYS = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 120))


def test_fitness_band_is_the_recent_median_and_flags_a_lasting_dip():
    acts = steady_runner(TODAY)
    band = cp.fitness_band(acts, TODAY)
    assert band["low"] == pytest.approx(0.9 * band["center"], abs=0.1)
    assert band["high"] == pytest.approx(1.1 * band["center"], abs=0.1)
    assert not band["below"] and not band["seasonal"]
    broke = steady_runner(TODAY, gap=(TODAY - timedelta(days=30), TODAY))      # un mois sans courir
    assert cp.fitness_band(broke, TODAY)["below"]
    assert cp.fitness_band(acts[:5], TODAY) is None                            # pas assez d'historique


def test_seasonal_dip_is_recognised_from_last_year():
    gaps = [(TODAY - timedelta(days=30), TODAY), (TODAY - timedelta(days=395), TODAY - timedelta(days=365))]
    acts = []
    for g in gaps:
        acts = [a for a in (acts or steady_runner(TODAY, weeks=70)) if not g[0] <= a["start"].date() <= g[1]]
    band = cp.fitness_band(acts, TODAY)
    assert band["below"] and band["seasonal"]


def test_maintenance_keeps_fitness_in_the_band_with_one_quality_session_and_a_light_week():
    acts = steady_runner(TODAY)
    plan = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170)
    assert plan["maintenance"] and plan["mode"] == "maintien" and not plan["trail"]
    assert len(plan["weeks"]) == cp.MAINT_WEEKS
    assert [w["kind"] for w in plan["weeks"]].count("allégée") == 2               # 3 + 1, deux fois
    for w in plan["weeks"]:
        assert sum(1 for s in w["sessions"] if s["hard"]) <= 1                     # une séance de qualité
        assert w["phase"] == "maintien"
    b = plan["band"]
    assert all(b["low"] - 0.5 <= w["fitness_end"] <= b["high"] + 0.5 for w in plan["weeks"])
    longs = [s["minutes"] for w in plan["weeks"] for s in w["sessions"] if s["type"] == "sortie longue"]
    assert longs and max(longs) <= max(plan["long_usual"], cp.MIN_LONG_MIN)      # pas de progression


def test_maintenance_offers_a_test_now_and_then_with_the_usual_session_as_alternative():
    plan = cp.build_maintenance(TODAY, steady_runner(TODAY), MAINT_DAYS, None, [], {}, 170,
                                {"start": TODAY - timedelta(days=3)})
    tests = [s for w in plan["weeks"] for s in w["sessions"] if s["type"] == "test"]
    assert len(tests) == 1 and tests[0]["key"] and tests[0]["alt"]["hard"]
    assert "Facultatif" in tests[0]["description"]


def test_after_a_break_the_runner_gets_a_progressive_reprise():
    acts = steady_runner(TODAY, gap=(TODAY - timedelta(days=30), TODAY))
    plan = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170)
    assert plan["mode"] == "reprise" and plan["position"] == "below"
    reprise = [w for w in plan["weeks"] if w["phase"] == "reprise"]
    assert reprise and plan["weeks"][0]["phase"] == "reprise"
    charge = [w["target_load"] for w in plan["weeks"] if w["kind"] == "charge" and w["phase"] == "reprise"]
    assert all(b <= a * 1.1 + 1 for a, b in zip(charge, charge[1:], strict=False))   # +10 % au plus
    assert plan["weeks"][-1]["fitness_end"] > plan["start_fitness"]


def test_above_the_band_the_runner_is_not_pulled_down():
    acts = steady_runner(TODAY, weeks=30)
    acts += [{**run(TODAY - timedelta(days=d), 120, 120, 0.0), "id": 1000 + d, "terrain": "road",
              "distance_km": 20, "gain_m": 50} for d in range(1, 15, 2)]
    plan = cp.build_maintenance(TODAY, acts, avail(*[(d, "oui", 120) for d in range(6)]), None, [], {}, 170)
    assert plan["position"] == "above"
    first = plan["weeks"][0]
    assert first["target_load"] >= cp.weekly_load_for(plan["band"]["high"], plan["band"]["high"]) - 1


def test_maintenance_starts_with_the_recovery_of_the_last_race():
    acts = steady_runner(TODAY)
    race = {**side_race(TODAY - timedelta(days=3), "A", km=30, gain=1500, minutes=240), "race_date":
            (TODAY - timedelta(days=3)).isoformat()}
    plan = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170,
                                {"start": TODAY - timedelta(days=2)}, [race])
    assert plan["mode"] == "récupération" and plan["recovery_until"] > TODAY.isoformat()
    assert plan["weeks"][0]["events"] and not any(s["hard"] for s in plan["weeks"][0]["sessions"])


def test_maintenance_follows_the_runner_orientation_on_trail():
    acts = [{**a, "terrain": "trail", "gain_m": 400} for a in steady_runner(TODAY)]
    assert cp.trail_oriented(acts, TODAY)
    plan = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170)
    assert plan["trail"]


# ---------- orientation et semaines particulières (étape 8) ----------

def test_period_levels_set_sessions_and_easy_days():
    a = avail((0, "oui", 50), (1, "oui", 60), (3, "oui", 80), (5, "oui", 120))
    days = cp.chosen_days(a, None)
    mon = date(2026, 12, 21)
    week_long = {"start": "2026-12-21", "end": "2026-12-27", "sessions": None}
    minimum = cp.period_days(days, mon, [{**week_long, "kind": "noel"}], a)       # niveau par défaut
    assert len(minimum) == cp.MINIMUM_SESSIONS and all(d["easy_only"] for d in minimum)
    none = cp.period_days(days, mon, [{**week_long, "kind": "vacances", "level": "aucune"}], a)
    assert none == []
    light = cp.period_days(days, mon, [{**week_long, "kind": "chargee"}], a)
    assert [d["weekday"] for d in light] == [0, 1, 3, 5] and not any(d["easy_only"] for d in light)
    pain = cp.period_days(days, mon, [{**week_long, "kind": "douleur"}], a)
    assert len(pain) == 4 and all(d["easy_only"] for d in pain)


def test_pain_suspends_progression_and_a_break_is_followed_by_a_reprise():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    race = {**RACE, "race_date": "2027-03-28"}
    alone = {w["monday"]: w for w in cp.build_plan(race, TODAY, acts, days, None, [], {}, 170)["weeks"]}
    pain = {"kind": "douleur", "start": "2026-11-30", "end": "2026-12-06", "sessions": None}
    plan = {w["monday"]: w for w in cp.build_plan(race, TODAY, acts, days, None, [], {}, 170,
                                                  {"periods": [pain]})["weeks"]}
    w = plan["2026-11-30"]
    assert not any(s["hard"] for s in w["sessions"]) and w["periods"][0]["suspend"]
    assert w["target_load"] <= plan["2026-11-23"]["target_load"] + 1            # pas de hausse
    assert plan["2026-12-07"]["periods"][0]["kind"] == "reprise"
    holiday = {"kind": "vacances", "level": "aucune", "start": "2026-12-14", "end": "2026-12-25",
               "sessions": None}
    plan = {w["monday"]: w for w in cp.build_plan(race, TODAY, acts, days, None, [], {}, 170,
                                                  {"periods": [holiday]})["weeks"]}
    assert plan["2026-12-14"]["sessions"] == []
    eve = [s for s in plan["2026-12-07"]["sessions"] if s["date"] == "2026-12-13"]
    assert not any(s["hard"] for s in eve)                       # pas de séance dure la veille
    assert any(e["kind"] == "reprise" for e in plan["2026-12-28"]["periods"])
    assert plan["2026-12-28"]["target_load"] < alone["2026-12-28"]["target_load"]


def test_nuance_brings_more_hills_and_warns_when_it_strays_from_the_race():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    road = {**RACE, "race_date": "2027-03-28", "gain_m": 50, "distance_m": 21100, "duration_s": 6000}
    base = cp.build_plan(road, TODAY, acts, days, None, [], {}, 170)
    hills = cp.build_plan(road, TODAY, acts, days, None, [], {}, 170, {"nuance": "côtes"})
    count = lambda p: sum(1 for w in p["weeks"] for s in w["sessions"] if s["type"] in cp.HILL_TYPES)  # noqa: E731
    assert count(hills) > count(base)
    assert hills["nuance_warning"] and "plate" in hills["nuance_warning"]
    assert base["nuance_warning"] is None
    assert cp.nuance_warning("vitesse", {**RACE, "duration_s": 4 * 3600})
    assert cp.nuance_warning("endurance", {**RACE, "duration_s": 1500, "gain_m": 0})
    six = avail(*[(d, "oui", 60) for d in range(6)])
    endurance = cp.build_plan(road, TODAY, acts, six, None, [], {}, 170, {"nuance": "endurance"})
    assert all(sum(1 for s in w["sessions"] if s["hard"] and s["type"] != "course") <= 1
               for w in endurance["weeks"])


def test_orientation_changes_what_maintenance_works_on():
    acts = steady_runner(TODAY)
    five = avail((0, "oui", 60), (1, "oui", 60), (2, "oui", 60), (3, "oui", 60), (5, "oui", 120))
    plan = cp.build_maintenance(TODAY, [{**a, "terrain": "trail"} for a in acts], five, None, [], {}, 170,
                                {"orientation": "vitesse"})
    assert not plan["trail"] and plan["orientation_label"].startswith("Vitesse")
    keys = {s["type"] for w in plan["weeks"] if w["kind"] == "charge" for s in w["sessions"] if s["hard"]}
    assert keys <= {"vma", "seuil", "pyramide", "fartlek", "tempo", "test"} and "vma" in keys
    longue = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170, {"orientation": "route_longue"})
    longest = max(s["minutes"] for w in longue["weeks"] for s in w["sessions"]
                  if s["type"] == "sortie longue")
    assert longest > longue["long_usual"]
    reprise = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170, {"orientation": "reprise"})
    assert reprise["weeks"][0]["phase"] == "reprise" or reprise["start_fitness"] >= reprise["band"]["center"]
    trail = cp.build_maintenance(TODAY, acts, MAINT_DAYS, None, [], {}, 170, {"orientation": "trail"})
    assert trail["trail"] and {w["phase"] for w in trail["weeks"]} == {"trail"}


# ---------- deux propositions, parcours, monotonie (étape 9) ----------

def test_each_session_has_a_second_proposal_with_the_same_role():
    days = cp.chosen_days(avail((0, "oui", 50), (1, "oui", 60), (3, "oui", 70), (5, "oui", 150)), None)
    w = cp.build_week(week(), days, 300, RATES, RACE, {}, [], 170, 0)
    q = next(s for s in w["sessions"] if s["hard"])
    assert q["alt"]["hard"] and q["alt"]["type"] != q["type"]
    assert (q["type"] in cp.wk.HILLY) != (q["alt"]["type"] in cp.wk.HILLY)       # l'autre terrain
    long = next(s for s in w["sessions"] if s["type"] == "sortie longue")
    assert long["alt"]["type"] == "sortie longue" and long["alt"]["label"] != long["label"]
    easy = [s for s in w["sessions"] if s["type"] in ("footing", "footing vallonné")]
    assert all(s["alt"]["type"] != s["type"] and s["alt"]["minutes"] == s["minutes"] for s in easy)


def test_choosing_the_second_proposal_replaces_it_while_the_session_is_the_same():
    acts = [run(TODAY - timedelta(days=i), 60, 90, 0.0) for i in range(1, 200, 2)]
    days = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 60), (5, "oui", 150))
    plan = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170)
    w = plan["weeks"][1]
    q = next(s for s in w["sessions"] if s["hard"] and s.get("alt"))
    alt_label, before = q["alt"]["label"], w["planned_load"]
    cp.apply_choices(plan, {q["date"]: q["label"], "2026-12-25": "Autre chose"})
    chosen = next(s for s in w["sessions"] if s["date"] == q["date"] and s["hard"])
    assert chosen["label"] == alt_label and chosen["chosen"] and chosen["alt"]["label"] == q["label"]
    assert chosen["key"] == q["key"] and isinstance(w["planned_load"], int)
    assert before > 0
    stale = cp.build_plan({**RACE, "race_date": "2027-03-28"}, TODAY, acts, days, None, [], {}, 170)
    cp.apply_choices(stale, {q["date"]: "Une séance qui n'existe plus"})
    assert not any(s.get("chosen") for w in stale["weeks"] for s in w["sessions"])


def test_routes_rotate_among_the_runner_habitual_routes():
    acts = []
    for k, (rid, minutes) in enumerate([(1, 45), (2, 50), (3, 120)] * 4):
        acts.append({**run(TODAY - timedelta(days=3 + 5 * k), 50, minutes, 0.0), "id": 100 + k,
                     "route_id": rid, "distance_km": minutes / 6, "gain_m": 20, "name": f"Parcours {rid}"})
    routes = cp.habitual_routes(acts, TODAY)
    assert {r["id"] for r in routes} == {1, 2, 3} and all(r["runs"] == 4 for r in routes)
    on = lambda d: (TODAY + timedelta(days=d)).isoformat()  # noqa: E731
    weeks = [{"sessions": [{"date": on(d), "type": "footing", "minutes": 45},
                           {"date": on(d + 1), "type": "footing",
                            "minutes": 50, "habit": "Bastille"}]} for d in (1, 8)]
    cp.suggest_routes(weeks, routes, TODAY)
    picked = [w["sessions"][0]["route"]["name"] for w in weeks]
    assert picked[0] != picked[1]                                         # on varie
    assert "route" not in weeks[0]["sessions"][1]                         # l'habitude reste l'habitude


def test_monotony_compares_the_week_with_the_runner_own_weeks():
    assert cp.foster([50] * 7) is None                                    # écart-type nul
    assert cp.foster([60, 0, 60, 0, 60, 0, 120]) < cp.foster([60, 50, 60, 50, 60, 50, 60])
    acts = []
    start = cp.monday(TODAY) - timedelta(weeks=30)
    for w in range(30):
        pattern = [60, 0, 40, 0, 50, 0, 100] if w < 29 else [50, 45, 50, 45, 50, 45, 50]
        for k, load in enumerate(pattern):
            if load:
                acts.append(run(start + timedelta(weeks=w, days=k), load, 60, 0.0))
    m = cp.monotony(acts, TODAY)
    assert m["high_last"] and m["last"] > m["fence"]
    assert cp.monotony(acts[:10], TODAY) is None


def test_library_lists_every_family_with_the_runner_paces():
    lib = cp.wk.library({"lthr": 170, "threshold": 290, "vma": 250, "easy": 360, "easy_vam": 400})
    assert len(lib) >= 7 and all(f["sessions"] for f in lib)
    labels = {s["label"] for f in lib for s in f["sessions"]}
    assert {"Fartlek", "Pyramide", "Seuil", "Tempo", "Côtes courtes", "Sortie longue progressive"} <= labels
