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
    assert work["target"] == "4:52 à 5:04 /km · FC 162 à 170 · effort 7/10"
    easy = wk.easy_steps(60, P)[0]
    assert "environ 10 km" in easy["text"] and "FC sous 153" in easy["target"]
    hill = next(x for x in wk.hills_long(0, P)["steps"] if x["kind"] == "work")
    assert "/km" not in hill["target"] and "FC 162 à 170" in hill["target"]   # en côte : FC et sensation


def test_fit_steps_down_then_shortens_warmup_when_the_day_is_short():
    assert wk.fit(lambda lv, compact=False: wk.seuil(lv, P, compact), 5, 200)["minutes"] > 60
    s = wk.fit(lambda lv, compact=False: wk.seuil(lv, P, compact), 5, 55)
    assert s["minutes"] <= 55 and "3 × 8 min" in s["steps"][1]["text"]
    tight = wk.fit(lambda lv, compact=False: wk.hills_long(lv, P, compact), 3, 45)
    assert tight["steps"][0]["text"].startswith("Échauffement 10 min")
