from datetime import date, datetime

from app import coach_week as cw

MONDAY = date(2026, 11, 2)
TODAY = date(2026, 11, 4)                 # mercredi


def session(day, type_="footing", minutes=40, hard=False, key=False, **kw):
    d = date(2026, 11, 2 + day)
    return {"weekday": day, "date": d.isoformat(), "type": type_, "label": type_, "minutes": minutes,
            "hard": hard, "key": key, **kw}


def run(day, minutes, hard_share=0.0, id_=None, km=None, hour=12):
    """Sortie du jour `day` (0 = lundi), temps par zone : hard_share en zone 4."""
    total = minutes * 60
    return {"id": id_ or day * 10 + hour, "name": "Sortie", "start": datetime(2026, 11, 2 + day, hour),
            "moving_duration_s": total, "distance_km": km or minutes / 6, "gain_m": 50, "hrss": minutes,
            "zone1_s": total * (1 - hard_share), "zone2_s": 0, "zone3_s": 0, "zone4_s": total * hard_share,
            "zone5_s": 0}


def week(sessions, phase="développement"):
    return {"monday": MONDAY.isoformat(), "phase": phase, "kind": "charge", "sessions": sessions,
            "minutes": sum(s["minutes"] or 0 for s in sessions if not s.get("optional")),
            "planned_load": 200, "gain_m": 300}


def test_runs_are_matched_on_the_same_day_with_their_role():
    sessions = [session(0), session(1, "seuil", 60, hard=True, key=True), session(3),
                session(5, "sortie longue", 90)]
    m = cw.match(sessions, [run(0, 42), run(1, 58, hard_share=0.3)], MONDAY, TODAY)
    s = m["sessions"]
    assert [x["status"] for x in s] == ["faite", "faite", "à venir", "à venir"]
    assert s[0]["done"]["role"] == "easy" and s[0]["note"] is None
    assert s[1]["done"]["role"] == "hard" and s[1]["note"] is None
    assert m["extra"] == []


def test_a_session_done_a_day_later_counts_as_moved_and_a_missed_one_is_not_made_up():
    sessions = [session(0), session(1, "sortie longue", 80), session(3)]
    m = cw.match(sessions, [run(2, 78)], MONDAY, TODAY)
    s = m["sessions"]
    assert s[0]["status"] == "passée"                      # jamais rattrapée, simplement passée
    assert s[1]["status"] == "faite" and s[1]["done"]["role"] == "long"
    assert "1 jour plus tard" in s[1]["note"]
    assert s[2]["status"] == "à venir"


def test_a_run_far_from_any_session_counts_as_extra():
    sessions = [session(5, "sortie longue", 90)]
    m = cw.match(sessions, [run(0, 30)], MONDAY, TODAY)
    assert m["sessions"][0]["status"] == "à venir"
    assert len(m["extra"]) == 1 and m["extra"][0]["minutes"] == 30


def test_same_day_wins_over_the_role_and_differences_are_noted_without_judgement():
    # footing prévu le lundi, séance faite le lundi : rapprochés, l'écart est noté
    sessions = [session(0, minutes=40), session(1, "seuil", 60, hard=True, key=True)]
    m = cw.match(sessions, [run(0, 25, hard_share=0.4)], MONDAY, TODAY)
    s = m["sessions"]
    assert s[0]["status"] == "faite"
    assert "plus courte (25 min au lieu de 40)" in s[0]["note"]
    assert "plus soutenue que prévu" in s[0]["note"]
    assert s[1]["status"] == "passée"


def test_a_double_day_gives_the_second_run_to_a_nearby_session():
    sessions = [session(0, minutes=40), session(1, minutes=40)]
    m = cw.match(sessions, [run(0, 40, hour=8), run(0, 40, hour=19)], MONDAY, TODAY)
    assert [x["status"] for x in m["sessions"]] == ["faite", "faite"]
    assert m["extra"] == []


def test_runs_after_today_and_outside_the_week_are_ignored():
    sessions = [session(0)]
    acts = [{**run(0, 40), "start": datetime(2026, 11, 1, 12)}, run(4, 40)]
    m = cw.match(sessions, acts, MONDAY, TODAY)
    assert m["sessions"][0]["status"] == "passée" and m["extra"] == []


def test_a_confirmed_race_is_matched_to_the_race_session():
    sessions = [session(1, "seuil", 50, hard=True), session(2, "course", 100, hard=True, key=True)]
    m = cw.match(sessions, [run(2, 105, hard_share=0.8, id_=99)], MONDAY, TODAY, race_ids={99})
    assert m["sessions"][1]["status"] == "faite" and m["sessions"][1]["done"]["role"] == "race"
    assert m["sessions"][0]["status"] == "passée"


def test_what_can_skip_is_optional_then_shortest_footings_never_key_long_or_race():
    sessions = [session(2, minutes=50), session(3, minutes=35), session(4, "seuil", 60, hard=True, key=True),
                session(5, "sortie longue", 100), session(6, "sortie longue", 80, optional=True),
                session(0, minutes=30)]
    rows = cw.match(sessions, [run(0, 30)], MONDAY, TODAY)["sessions"]
    skip = cw.skippable(rows, TODAY)
    assert [(s["type"], s["minutes"]) for s in skip] == [("sortie longue", 80), ("footing", 35)]


def test_week_view_sums_what_was_done_against_the_plan():
    sessions = [session(0, minutes=40), session(1, "seuil", 60, hard=True, key=True),
                session(5, "sortie longue", 90),
                session(6, minutes=40, optional=True)]
    v = cw.week_view(week(sessions), [run(0, 40), run(1, 60, hard_share=0.3), run(2, 20)], TODAY)
    assert v["planned"]["sessions"] == 3 and v["planned"]["minutes"] == 190
    assert v["done"]["sessions"] == 2 and v["done"]["runs"] == 3          # la sortie en plus compte aussi
    assert v["done"]["minutes"] == 120 and v["done"]["load"] == 120
    assert v["key"]["type"] == "seuil" and "développement" in v["key_reason"]
    assert v["today_session"] is None


def test_key_reason_follows_the_session_and_the_phase():
    assert "endurance" in cw.key_reason({"type": "sortie longue"}, "foncier")
    assert "course" in cw.key_reason({"type": "course"}, "spécifique")
    assert "effort de la course" in cw.key_reason({"type": "seuil"}, "spécifique")
