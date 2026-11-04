from datetime import date, datetime, timedelta

import pytest

from app import coach, coach_live, coach_notify, db, settings, tracked
from app import coach_plan as cp
from app import coach_review as cr
from app.scheduler import DailyScheduler

MONDAY = date(2026, 11, 2)


# ---------- verdict et bilan (fonctions pures) ----------

def test_verdict_takes_the_lowest_of_sessions_and_load():
    assert cr.verdict({"sessions": 4, "load": 200}, {"sessions": 4, "load": 190})["key"] == "good"
    v = cr.verdict({"sessions": 4, "load": 200}, {"sessions": 4, "load": 120})     # charge 60 %
    assert v["key"] == "partial" and v["share_pct"] == 60 and v["sessions_pct"] == 100
    assert cr.verdict({"sessions": 4, "load": 200}, {"sessions": 1, "load": 210})["key"] == "low"
    over = cr.verdict({"sessions": 2, "load": 100}, {"sessions": 2, "load": 300})   # plafonnée à 100 %
    assert over["key"] == "good" and over["share_pct"] == 100 and over["load_pct"] == 300
    assert cr.verdict({"sessions": 0, "load": 0}, {"sessions": 0, "load": 30})["key"] == "none"


def test_form_state_is_relative_to_fitness():
    low = cr.form_state(20.0, 27.0)                  # −35 % de la fitness : surcharge
    assert low["pct"] == -35 and low["zone"] == "overload" and low["low"]
    assert not cr.form_state(20.0, 24.0)["low"]      # −20 % : entraînement productif
    assert not cr.form_state(0.0, 0.0)["low"]


def session(day, status, key=False, label="Footing", optional=False, done_day=None):
    s = {"date": (MONDAY + timedelta(days=day)).isoformat(), "day": cp.WEEKDAYS[day], "label": label,
         "status": status, "key": key, "optional": optional}
    if done_day is not None:
        s["done"] = {"date": (MONDAY + timedelta(days=done_day)).isoformat()}
    return s


def week_view(sessions, done=(2, 90), planned=(4, 180), extra=()):
    return {"monday": MONDAY.isoformat(), "sessions": sessions, "extra": list(extra),
            "key": next((s for s in sessions if s["key"]), None),
            "planned": {"sessions": planned[0], "load": planned[1], "minutes": 200, "gain_m": 0},
            "done": {"sessions": done[0], "load": done[1], "runs": done[0], "minutes": 100, "gain_m": 0}}


PLAN = {"weeks": [{"monday": MONDAY.isoformat(), "fitness_end": 20.0},
                  {"monday": "2026-11-09", "kind": "charge", "phase": "foncier", "planned_load": 190}]}


def test_review_says_what_happened_without_judging():
    w = week_view([session(0, "faite", done_day=1), session(2, "passée"),
                   session(3, "faite", key=True, label="Seuil", done_day=3), session(5, "passée")])
    r = cr.review(w, PLAN, {"fitness": 21.0, "fatigue": 20.0}, [
        {"name": "Semi", "priority": "A", "race_date": "2027-03-01", "before_s": 6000, "after_s": 5980}])
    assert r["verdict"]["key"] == "partial"
    text = " ".join(r["lines"])
    assert "2 séances faites sur 4" in text and "Séance clé, Seuil : faite" in text
    assert "pas de rattrapage" in text and "un autre jour" in text and "en avance" in text
    assert r["fitness"] == {"planned": 20.0, "actual": 21.0, "ahead": True}
    assert r["races"][0]["delta_s"] == -20 and r["next"]["load"] == 190 and r["pending"] == 0


def test_review_on_sunday_is_provisional_while_a_session_is_left():
    w = week_view([session(0, "faite", done_day=0),
                   session(6, "aujourd'hui", key=True, label="Sortie longue")],
                  done=(1, 40), planned=(2, 120))
    r = cr.review(w, PLAN, {"fitness": 19.8, "fatigue": 19.0}, [])
    assert r["pending"] == 1 and any(line.startswith("Bilan provisoire") for line in r["lines"])
    assert any("encore à faire" in line for line in r["lines"])
    assert any("comme prévu" in line for line in r["lines"]) and not r["fitness"]["ahead"]


def summary(ahead=False, low=False, load=190):
    return {"next": {"monday": "2026-11-09", "kind": "charge", "phase": "foncier", "load": load},
            "fitness": {"ahead": ahead}, "form": {"low": low, "pct": -35 if low else 0}}


def test_adjustment_follows_the_answers_and_the_real_form():
    assert cr.adjustment(None, summary()) is None
    assert cr.adjustment({"next_week": "normale", "feeling": "normal"}, summary()) is None
    tired = cr.adjustment({"feeling": "fatigué"}, summary())
    assert tired["light"].startswith("Tu te sens fatigué") and tired["monday"] == "2026-11-09"
    assert "surcharge" in cr.adjustment(None, summary(low=True))["light"]
    assert cr.adjustment({"next_week": "chargée"}, summary())["busy"]
    assert cr.adjustment({"next_week": "libre"}, summary())["free"]
    assert cr.adjustment(None, summary(ahead=True))["cap_load"] == 190
    assert cr.adjustment({"feeling": "fatigué"}, {"next": None}) is None        # plus de semaine
    assert cr.orientation(None, summary()) == ["Semaine suivante telle que prévue par le plan."]
    assert "sans accélérer" in " ".join(cr.orientation(None, summary(ahead=True)))


def test_clean_answers():
    answers = {"next_week": "libre", "feeling": None}
    assert cr.clean_answers(answers) == answers
    with pytest.raises(ValueError):
        cr.clean_answers({"feeling": "épuisé"})
    with pytest.raises(ValueError):
        cr.clean_answers([])


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    yield c
    c.close()


def test_answers_and_summary_are_stored_side_by_side(conn):
    cr.save_answers(conn, MONDAY, {"next_week": "chargée", "feeling": "frais"})
    cr.save_summary(conn, MONDAY, {"verdict": {"key": "good"}})
    cr.save_answers(conn, MONDAY, {"next_week": "libre", "feeling": None})
    row = cr.all_reviews(conn)["2026-11-02"]
    assert row["next_week"] == "libre" and row["feeling"] is None
    assert row["summary"] == {"verdict": {"key": "good"}}


# ---------- plan ancré et réajustements ----------

def run(day, hrss, minutes, hard_share=0.0, i=0):
    total = minutes * 60
    return {"id": i or day.toordinal(), "start": datetime(day.year, day.month, day.day, 8), "hrss": hrss,
            "moving_duration_s": total, "distance_km": minutes / 6, "gain_m": 0, "name": "Sortie",
            "zone1_s": total * (1 - hard_share), "zone2_s": 0, "zone3_s": total * hard_share,
            "zone4_s": 0, "zone5_s": 0}


def avail(*days):
    by = {d: (s, m) for d, s, m in days}
    return [{"weekday": d, "status": by.get(d, ("non", None))[0], "max_min": by.get(d, ("non", None))[1],
             "usual_min": None} for d in range(7)]


RACE = {"name": "Trail", "race_date": "2027-03-28", "gpx_id": None, "distance_m": 30000, "gain_m": 1500,
        "duration_s": 4 * 3600, "target_text": None}
ACTS = [run(date(2026, 11, 4) - timedelta(days=i), 50, 60) for i in range(1, 120, 2)]
DAYS = avail((0, "oui", 60), (1, "oui", 60), (3, "oui", 70), (5, "oui", 120), (6, "optionnel", 90))


def test_anchored_skeleton_keeps_phases_and_lets_light_weeks_arrive():
    start = date(2026, 11, 4)
    first = cp.skeleton(start, date(2027, 3, 28), 4 * 3600)
    later = cp.skeleton(start + timedelta(weeks=5), date(2027, 3, 28), 4 * 3600, start)
    assert later == first                         # même départ : mêmes semaines, phases et types
    drifting = cp.skeleton(start + timedelta(weeks=5), date(2027, 3, 28), 4 * 3600)
    assert [w["phase"] for w in drifting] != [w["phase"] for w in first[5:]]   # sans départ, elles glissent
    light = next(w for w in first if w["kind"] == "allégée")
    # le jour venu, la semaine allégée est la semaine en cours du plan (sans départ fixe, jamais)
    plan = cp.build_plan(RACE, light["monday"], ACTS, DAYS, None, [], {}, 170, {"start": start})
    assert plan["weeks"][0]["kind"] == "allégée" and plan["weeks"][0]["monday"] == light["monday"].isoformat()
    unanchored = cp.build_plan(RACE, light["monday"], ACTS, DAYS, None, [], {}, 170)
    assert unanchored["weeks"][0]["kind"] == "charge"


def test_rotation_moves_on_from_one_week_to_the_next():
    start = date(2026, 11, 4)
    a = cp.build_plan(RACE, start, ACTS, DAYS, None, [], {}, 170, {"start": start})
    b = cp.build_plan(RACE, start + timedelta(weeks=1), ACTS, DAYS, None, [], {}, 170, {"start": start})
    key = lambda w: next(s["label"] for s in w["sessions"] if s.get("key"))   # noqa: E731
    assert key(b["weeks"][0]) == key(a["weeks"][1]) != key(a["weeks"][0])


def adjusted(max_sessions=4, **adj):
    monday = "2026-11-02"
    return cp.build_plan(RACE, date(2026, 11, 4), ACTS, DAYS, max_sessions, [], {}, 170,
                         {"start": date(2026, 11, 4), "adjust": [{"monday": monday, **adj}]})["weeks"][0]


def test_tired_week_becomes_a_light_week():
    normal, light = adjusted(), adjusted(light="Fatigue")
    assert normal["kind"] == "charge" and light["kind"] == "allégée"
    assert light["target_load"] < normal["target_load"]
    assert light["adjust"] == [{"kind": "light", "text": "Fatigue"}]


def test_busy_week_drops_a_third_keeping_key_and_long_run():
    normal, busy = adjusted(), adjusted(busy=True)
    n = len([s for s in normal["sessions"] if not s.get("optional")])
    left = [s for s in busy["sessions"] if not s.get("optional")]
    assert len(left) == n - n // 3 and len(left) >= 2
    assert any(s.get("key") for s in left) and any(s["type"] == "sortie longue" for s in left)
    assert busy["planned_load"] < normal["planned_load"] and busy["adjust"][0]["kind"] == "busy"


def test_drop_for_busy_week_keeps_at_least_two_sessions():
    w = {"sessions": [
        {"type": "sortie longue", "hard": False, "minutes": 90, "label": "Sortie longue", "day": "samedi"},
        {"type": "seuil", "hard": True, "key": True, "minutes": 50, "label": "Seuil", "day": "mardi"}]}
    assert cp.drop_for_busy_week(w, {"easy": 40, "quality": 60}) == []
    w["sessions"] += [{"type": "footing", "hard": False, "minutes": 30, "label": "Footing", "day": "lundi"},
                      {"type": "footing", "hard": False, "minutes": 45, "label": "Footing", "day": "jeudi",
                       "habit": "Bastille"},
                      {"type": "footing", "hard": False, "minutes": 60, "label": "Footing", "day": "vendredi",
                       "optional": True}]
    dropped = cp.drop_for_busy_week(w, {"easy": 40, "quality": 60})
    # optionnelle d'abord, puis le footing le plus court (l'habitude en dernier) : 4 séances, une en moins
    assert [d["day"] for d in dropped] == ["vendredi", "lundi"]
    assert w["minutes"] == 90 + 50 + 45 and w["planned_load"] == round((135 * 40 + 50 * 60) / 60)


def test_free_week_opens_optional_days_without_raising_the_target():
    normal, free = adjusted(None), adjusted(None, free=True)
    assert 6 not in {s["weekday"] for s in normal["sessions"] if not s.get("optional")}   # bonus
    assert 6 in {s["weekday"] for s in free["sessions"] if not s.get("optional")}
    assert free["target_load"] == normal["target_load"] and free["adjust"][0]["kind"] == "free"


def test_ahead_of_plan_keeps_the_progression_without_speeding_up():
    normal = adjusted()
    capped = adjusted(cap_load=normal["target_load"] - 30)
    assert capped["target_load"] == normal["target_load"] - 30 and capped["adjust"][0]["kind"] == "cap"
    assert adjusted(cap_load=normal["target_load"] + 50)["adjust"] == []      # plafond qui ne joue pas


def test_plan_start_follows_creation_and_last_a_race():
    race = {"race_date": "2027-05-22", "created_at": "2026-11-04T11:00:00"}
    assert coach.plan_start(race, []) == date(2026, 11, 4)
    past = [{"priority": "A", "race_date": "2026-12-06"}, {"priority": "B", "race_date": "2026-12-20"}]
    assert coach.plan_start(race, past) == date(2026, 12, 7)


# ---------- coach sur une base de test : dimanche, lundi, mardi ----------

SUNDAY = date(2026, 11, 8)


@pytest.fixture
def live(config, conn, monkeypatch):
    """Une course A dans 20 semaines ajoutée le lundi 2 novembre, des sorties régulières avant."""
    acts = [run(date(2026, 11, 1) - timedelta(days=i), 50, 60, i=i + 1) for i in range(0, 120, 2)]
    acts += [run(date(2026, 11, 3), 45, 55, i=900)]                       # une sortie dans la semaine
    real = tracked.load_data
    monkeypatch.setattr(tracked, "load_data", lambda cfg, c: {**real(cfg, c), "acts": acts})
    race_id = coach.create(conn, {"name": "Semi", "race_date": "2027-03-21", "priority": "A", "gpx_id": None,
                                  "distance_m": 21097.5, "gain_m": 0.0, "target_s": 6300.0})
    with conn:
        conn.execute("UPDATE coach_races SET created_at='2026-11-02T08:00:00' WHERE id=?", (race_id,))
    settings.update(conn, "coach", {"availability": avail((0, "oui", 60), (2, "oui", 60), (5, "oui", 100))})
    return conn


def test_sunday_review_then_monday_adjusted_then_frozen(config, live):
    sunday = coach_live.Coach(config, live, SUNDAY)
    assert sunday.reviewable(MONDAY) and not sunday.reviewable(MONDAY - timedelta(days=7))   # avant le plan
    r = sunday.review(MONDAY, live)
    assert r["verdict"]["key"] in ("low", "partial") and r["next"]["monday"] == "2026-11-09"
    assert cr.all_reviews(live) == {}                       # pas figé : la semaine n'est pas close
    cr.save_answers(live, MONDAY, {"next_week": "normale", "feeling": "fatigué"})

    monday = coach_live.Coach(config, live, date(2026, 11, 9))
    plain = monday.week_plan(date(2026, 11, 9))["weeks"][0]
    assert plain["kind"] == "allégée" and plain["adjust"][0]["kind"] == "light"
    assert monday.week_view(date(2026, 11, 9))["adjust"][0]["text"].startswith("Tu te sens fatigué")
    monday.review(MONDAY, live)
    assert cr.all_reviews(live)["2026-11-02"]["summary"] is None       # synchro du lundi pas faite

    tuesday = coach_live.Coach(config, live, date(2026, 11, 10))
    frozen = tuesday.review(MONDAY, live)
    assert cr.all_reviews(live)["2026-11-02"]["summary"] == frozen     # figé une fois la semaine close
    assert tuesday.week_plan(date(2026, 11, 9))["weeks"][0]["kind"] == "allégée"


def test_freshness_on_race_morning(config, live):
    co = coach_live.Coach(config, live, SUNDAY)
    f = co.freshness(SUNDAY)
    assert f["fitness"] > 0 and f["pct"] == round(f["form"] / f["fitness"] * 100)
    assert f["zone"] in ("transition", "fresh", "neutral", "optimal", "overload") and f["label"]


# ---------- notification ----------

def test_review_message_and_due_time():
    title, text = coach_notify.review_message({"verdict": {"label": "Semaine bien suivie"},
                                               "planned": {"sessions": 4, "load": 180},
                                               "done": {"sessions": 4, "load": 175}})
    assert title == "Bilan : semaine bien suivie" and text.startswith("4 séances sur 4, charge 175 pour 180")
    cfg = settings.DEFAULTS["notifications"]
    assert coach_notify.is_due(datetime(2026, 11, 8, 19), cfg, None)
    assert not coach_notify.is_due(datetime(2026, 11, 8, 18), cfg, None)          # avant l'heure
    assert not coach_notify.is_due(datetime(2026, 11, 7, 20), cfg, None)          # samedi
    assert not coach_notify.is_due(datetime(2026, 11, 8, 20), cfg, "2026-11-02")  # déjà envoyée
    assert not coach_notify.is_due(datetime(2026, 11, 8, 20), {**cfg, "review_enabled": False}, None)
    assert coach_notify.review_link({"public_url": "https://t.example"}) == "https://t.example/coach?vue=semaine#bilan"


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_send_posts_to_ntfy_with_utf8_title(config, monkeypatch):
    import dataclasses
    seen = []
    monkeypatch.setattr(coach_notify.urllib.request, "urlopen",
                        lambda req, timeout: seen.append(req) or FakeResponse())
    with pytest.raises(coach_notify.NotifyError):
        coach_notify.send(config, "t", "m")                                      # pas d'adresse
    cfg = dataclasses.replace(config, ntfy_url="https://ntfy.example/sujet", ntfy_token="jeton")
    coach_notify.send(cfg, "Bilan : semaine peu suivie", "Corps é", "https://t.example/coach")
    req = seen[0]
    assert req.full_url.startswith("https://ntfy.example/sujet?title=Bilan+%3A+semaine+peu+suivie")
    assert "click=https" in req.full_url and req.data == "Corps é".encode()
    assert req.get_header("Authorization") == "Bearer jeton"


class FakeSync:
    running = False

    def __init__(self):
        self.runs = 0

    def run(self, **kw):
        self.runs += 1


class FakeAccount:
    def is_configured(self):
        return True


def test_scheduler_sends_the_sunday_review_once_after_a_sync(config, live, monkeypatch):
    import dataclasses
    cfg = dataclasses.replace(config, ntfy_url="https://ntfy.example/sujet")
    sent = []
    monkeypatch.setattr(coach_notify, "send",
                        lambda c, title, text, click=None, tags=None: sent.append(title))
    sync = FakeSync()
    sched = DailyScheduler(cfg, sync, FakeAccount())
    assert not sched.sunday_review(datetime(2026, 11, 8, 18))
    assert sched.sunday_review(datetime(2026, 11, 8, 19, 5)) and sync.runs == 1
    assert sent and sent[0].startswith("Bilan : semaine")
    assert not sched.sunday_review(datetime(2026, 11, 8, 21))                      # une fois par semaine
    without = DailyScheduler(config, sync, FakeAccount())                         # sans ntfy
    assert not without.sunday_review(datetime(2026, 11, 15, 20))
