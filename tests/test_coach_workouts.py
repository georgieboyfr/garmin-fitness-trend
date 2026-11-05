import pytest

from app import coach_workouts as wk

P = {"threshold": 298.0, "vma": 255.0, "race": 300.0, "lthr": 170.0, "easy": 360.0}


@pytest.mark.parametrize("make", [lambda lv: wk.seuil(lv, P), lambda lv: wk.vma(lv, P),
                                  lambda lv: wk.hills_short(lv, P), lambda lv: wk.hills_long(lv, P),
                                  lambda lv: wk.race_pace(lv, P)])
def test_every_level_has_a_round_total_and_explicit_recovery(make):
    for level in range(6):
        s = make(level)
        assert s["minutes"] % 5 == 0 and s["hard"]
        kinds = [x["kind"] for x in s["steps"]]
        assert kinds[0] == "warmup" and kinds[-1] == "cooldown" and "work" in kinds
        rest = [x for x in s["steps"] if x["kind"] in ("recovery", "work") and ("trot" in x["text"]
                                                                              or "récupération" in x["text"])]
        assert rest, s["steps"]                                         # la récupération est toujours dite
        assert abs(sum(x["minutes"] for x in s["steps"]) - s["minutes"]) <= 2.5


def test_targets_give_pace_band_heart_rate_and_effort():
    work = next(x for x in wk.seuil(1, P)["steps"] if x["kind"] == "work")
    assert work["text"] == "3 × 10 min au seuil"
    assert work["target"] == "4:52 à 5:04 /km · FC 162 à 170 · effort 7/10, dur"
    assert work["intensity"]["hr"] == [162, 170] and work["intensity"]["feel"] == "dur"
    easy = wk.easy_steps(60, P)[0]
    assert "environ 10 km" in easy["text"] and "FC 128 à 144" in easy["target"]   # zone 1 de Friel, à défaut
    hill = next(x for x in wk.hills_long(0, P)["steps"] if x["kind"] == "work")
    assert "/km" not in hill["target"] and "FC 162 à 170" in hill["target"]   # en côte : FC et sensation


def test_fit_steps_down_then_shortens_warmup_when_the_day_is_short():
    assert wk.fit(lambda lv, compact=False: wk.seuil(lv, P, compact), 5, 200)["minutes"] > 60
    s = wk.fit(lambda lv, compact=False: wk.seuil(lv, P, compact), 5, 55)
    assert s["minutes"] <= 55 and "3 × 8 min" in s["steps"][1]["text"]
    tight = wk.fit(lambda lv, compact=False: wk.hills_long(lv, P, compact), 3, 45)
    assert tight["steps"][0]["text"].startswith("Échauffement 10 min")


@pytest.mark.parametrize("name", ["hills_short", "hills_medium", "hills_long", "power_hike", "downhill",
                                  "uphill_tempo"])
def test_hill_sessions_always_say_how_and_how_long_to_recover(name):
    s = getattr(wk, name)(1, P)
    rest = next(x for x in s["steps"] if x["kind"] == "recovery")
    assert any(w in rest["text"] for w in ("trot", "marchant")) and ("min" in rest["text"]
                                                                     or "sans forcer" in rest["text"])



HR = {**P, "hr_max": 190, "easy_hr": wk.easy_hr("karvonen", 190, 50)}


def test_easy_heart_rate_from_heart_rate_reserve_or_max():
    assert wk.easy_hr("karvonen", 190, 50) == (134, 148)         # 60 à 70 % de la FC de réserve
    assert wk.easy_hr("fcmax", 190, 50) == (124, 142)            # 65 à 75 % de la FC max
    assert wk.easy_hr("karvonen", None, None, 170) == (128, 144)  # sans FC max : zone 1 de Friel
    easy = wk.easy_steps(45, HR)[0]
    assert "FC 134 à 148" in easy["target"] and easy["intensity"]["hr_max_pct"] == [71, 78]
    steady = next(x for x in wk.steady_run(50, HR)["steps"] if x["kind"] == "work")
    assert steady["intensity"]["hr"][0] == 149                   # le soutenu commence où l'endurance finit


def test_vma_pace_depends_on_the_length_of_the_rep():
    short = next(x for x in wk.vma(0, P)["steps"] if x["kind"] == "work")   # 30/30
    long_ = next(x for x in wk.vma(5, P)["steps"] if x["kind"] == "work")   # 1 000 m
    assert short["intensity"]["vma_pct"] == 105 and long_["intensity"]["vma_pct"] == 95
    assert "95 % de la VMA" in long_["text"]


@pytest.mark.parametrize("make", [lambda: wk.seuil(2, P), lambda: wk.vma(3, P), lambda: wk.strides(45, P),
                                  lambda: wk.steady_run(50, P), lambda: wk.hill_sprints(1, P),
                                  lambda: wk.long_run("progressive", 90, P),
                                  lambda: wk.long_run("classique", 90, P, steady_finish=True),
                                  lambda: wk.long_run("variations", 100, P)])
def test_sessions_with_effort_end_with_ten_minutes_of_cooldown(make):
    s = make()
    assert s["steps"][-1]["kind"] == "cooldown" and s["steps"][-1]["minutes"] >= 10


def test_resized_session_keeps_its_cooldown_last():
    s = wk.resize(wk.vma(0, P), 20, P)
    assert [x["kind"] for x in s["steps"]][-1] == "cooldown"
    assert s["steps"][0]["text"].startswith("Échauffement 25 min") and s["steps"][-1]["minutes"] == 25


def test_hilly_long_run_puts_the_steady_block_in_the_middle():
    s = wk.long_run("vallonnée", 105, {**P, "easy_vam": 300}, km=False, steady_finish=True)
    kinds = [x["kind"] for x in s["steps"]]
    assert kinds == ["steady", "work", "steady"] and "au milieu" in s["steps"][1]["text"]
    assert "revenir" in s["steps"][2]["text"] and s["gain_m"] > 0


def test_flat_alternative_of_a_hilly_long_run_has_the_same_load():
    rates = {"easy": 40.0, "steady": 55.0, "quality": 60.0}
    main = wk.long_run("vallonnée", 100, P, km=False)
    alt = wk.long_alternative("foncier", "charge", True, 0, "vallonnée", 100, P, False, main, rates)
    assert alt.get("flat") and not alt.get("gain_m")
    assert wk.estimated_load(alt, rates) <= wk.estimated_load(main, rates) + 1
    assert wk.estimated_load(alt, rates) >= wk.estimated_load(main, rates) - 4


def test_race_specific_blocks_grow_with_the_race_distance():
    semi = {**P, "race_kind": "semi"}
    assert "3 × 2 km à allure semi" in wk.race_pace(0, semi)["steps"][1]["text"]
    assert "3 × 5 km" in wk.race_pace(9, semi)["steps"][1]["text"]
    ten = {**P, "race_kind": "10k"}
    assert "5 × 1 km à allure 10 km" in wk.race_pace(0, ten)["steps"][1]["text"]
    # en spécifique, l'allure course une semaine sur deux, au palier qui monte
    texts = [wk.quality("spécifique", "charge", 0, False, w, semi, 999)["steps"][1]["text"]
             for w in range(0, 8, 2)]
    assert texts == ["3 × 2 km à allure semi", "4 × 2 km à allure semi", "3 × 3 km à allure semi",
                     "2 × 5 km à allure semi"]


def test_no_downhill_session_close_to_the_race():
    for w in range(6):
        s = wk.quality("spécifique", "charge", 0, True, w, P, 999, no_downhill=True)
        assert s["type"] != "descente"
    assert "descentes" not in {wk.long_variant("développement", "charge", True, w, True) for w in range(6)}
