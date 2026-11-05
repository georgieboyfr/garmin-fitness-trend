from datetime import date, datetime, timedelta

from app import vma_tests

TODAY = date(2026, 11, 5)


def act(i, days_ago, name="Footing", minutes=50, terrain="road"):
    return {"id": i, "start": datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()),
            "name": name, "description": None, "terrain": terrain, "moving_duration_s": minutes * 60}


def five(i, kmh):
    return {"id": i, "terrain": "road", "kind": "duration", "key": 300, "value": kmh / 3.6 * 300}


def test_a_short_all_out_run_or_a_named_test_is_proposed_not_a_race():
    acts = [act(1, 200, "Footing"), act(2, 100, "Fractionné", 70), act(3, 10, "Séance", 45),
            act(4, 5, "Test VMA demi-cooper", 40), act(5, 3, "10 km de Grenoble", 45)]
    efforts = [five(1, 15.2), five(2, 14.0), five(3, 15.0), five(4, 13.0), five(5, 15.1)]
    found = {c["id"]: c for c in vma_tests.candidates(acts, efforts, {5}, TODAY)}
    assert 3 in found and "meilleur 5 min" in found[3]["reasons"][0] and found[3]["vma_kmh"] == 15.0
    assert 4 in found and "mot-clé" in found[4]["reasons"][0]          # nommé « test » : proposé
    assert 5 not in found                                               # une course confirmée
    assert 2 not in found and 1 not in found                            # trop lent, ou trop ancien


def test_latest_vma_is_the_most_recent_of_admin_and_tests():
    vmas = [{"date": "2026-09-01", "kmh": 15.0}, {"date": "2026-11-04", "kmh": 16.0}]
    assert vma_tests.latest(vmas)["kmh"] == 16.0
    assert vma_tests.latest(vmas, date(2026, 10, 1))["kmh"] == 15.0
    assert vma_tests.latest([], TODAY) is None
