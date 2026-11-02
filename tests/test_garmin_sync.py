import io
import zipfile
from datetime import date, datetime

import pytest
from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

from app import db, settings
from app.garmin_sync import (
    GarminSync,
    SyncAlreadyRunning,
    extract_fit,
    month_ranges,
    parse_activity,
    summary_text,
)
from app.scheduler import DailyScheduler, is_due

FIT = b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT" + b"\x00" * 20


def zipped(data, name="123_ACTIVITY.fit"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, data)
    return buf.getvalue()


def garmin_act(act_id, local, name="Course", type_key="running", gmt=None):
    return {
        "activityId": act_id, "activityName": name,
        "startTimeLocal": local, "startTimeGMT": gmt or local,
        "activityType": {"typeKey": type_key},
        "distance": 10000.0, "duration": 3000.0, "movingDuration": 2950.0,
        "averageHR": 150.0, "maxHR": 175.0,
    }


class FakeClient:
    def __init__(self, activities):
        self.activities = activities
        self.list_calls = []
        self.downloads = []
        self.fail_download = {}

    def get_activities_by_date(self, start, end):
        self.list_calls.append((start, end))
        return [a for a in self.activities if start <= a["startTimeLocal"][:10] <= end]

    def download_activity(self, act_id, dl_fmt=None):
        self.downloads.append(act_id)
        if act_id in self.fail_download:
            raise self.fail_download[act_id]
        return zipped(FIT)


class FakeAccount:
    def __init__(self, client):
        self._client = client
        self.errors = []
        self.synced = []

    def client(self):
        if isinstance(self._client, Exception):
            raise self._client
        return self._client

    def is_configured(self):
        return True

    def record_error(self, e):
        self.errors.append(e)

    def invalidate(self):
        pass

    def record_sync(self, n):
        self.synced.append(n)


@pytest.fixture
def setup(config):
    config.ensure_dirs()
    conn = db.connect(config.db_path)
    db.migrate(conn)
    settings.update(conn, "garmin_sync", {"history_start": "2026-01-01"})
    yield config, conn
    conn.close()


def make_sync(config, client, today=date(2026, 3, 10)):
    sleeps = []
    sync = GarminSync(config, FakeAccount(client), sleep=sleeps.append, today=lambda: today)
    return sync, sleeps


def rows(conn):
    return {r["id"]: dict(r) for r in conn.execute("SELECT * FROM activities")}


# ---------- fonctions pures ----------

def test_month_ranges():
    assert month_ranges(date(2025, 11, 20), date(2026, 1, 5)) == [
        (date(2025, 11, 20), date(2025, 11, 30)),
        (date(2025, 12, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 1, 5)),
    ]
    assert month_ranges(date(2024, 2, 1), date(2024, 2, 29)) == [(date(2024, 2, 1), date(2024, 2, 29))]


def test_parse_activity():
    a = parse_activity(garmin_act(42, "2026-01-20 12:14:54", gmt="2026-01-20 11:14:54"))
    assert a["id"] == 42
    assert a["start_time_utc"] == "2026-01-20T11:14:54Z"
    assert a["start_time_local"] == "2026-01-20T12:14:54"
    assert a["activity_type"] == "running"
    assert parse_activity({"activityId": 1}) is None
    assert parse_activity({**garmin_act(1, "2026-01-01 10:00:00"), "startTimeGMT": "pas une date"}) is None


def test_extract_fit():
    assert extract_fit(zipped(FIT)) == FIT
    assert extract_fit(FIT) == FIT
    with pytest.raises(ValueError, match="pas un FIT"):
        extract_fit(b"<html>erreur</html>")
    with pytest.raises(ValueError, match="sans fichier"):
        extract_fit(zipped(b"x", name="readme.txt"))


def test_summary_text():
    assert summary_text({}) == "rien de nouveau"
    assert summary_text({"new": 2, "downloaded": 2}) == "2 nouvelle(s) activité(s), 2 FIT téléchargé(s)"


# ---------- synchro ----------

def test_first_import_lists_every_month_and_downloads(setup):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-01-05 08:00:00"), garmin_act(2, "2026-02-14 18:30:00"),
                         garmin_act(3, "2026-03-01 09:00:00", type_key="cycling")])
    sync, sleeps = make_sync(config, client)
    counts = sync.run()
    assert client.list_calls == [("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28"),
                                 ("2026-03-01", "2026-03-10")]
    assert counts == {"new": 3, "downloaded": 3}
    assert sorted(client.downloads) == ["1", "2", "3"]
    assert (config.fit_dir / "1.fit").read_bytes() == FIT
    assert {r["fit_status"] for r in rows(conn).values()} == {"stored"}
    assert len(sleeps) == 2 + 2  # entre les appels, pas après le dernier
    assert settings.get_state(conn, "garmin_first_import_done") is True
    run = conn.execute("SELECT * FROM sync_runs").fetchone()
    assert run["status"] == "ok" and "3 nouvelle(s)" in run["summary"]
    assert sync.account.synced == [3]
    assert not sync.running and sync.progress == {}


def test_existing_fit_is_reused_without_download(setup):
    config, conn = setup
    (config.fit_dir / "1.fit").write_bytes(FIT)
    client = FakeClient([garmin_act(1, "2026-01-05 08:00:00")])
    sync, _ = make_sync(config, client)
    assert sync.run() == {"new": 1, "reused": 1}
    assert client.downloads == []
    assert rows(conn)[1]["fit_status"] == "stored"


def test_second_run_is_incremental_and_idempotent(setup):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-01-05 08:00:00"), garmin_act(2, "2026-03-05 08:00:00")])
    sync, _ = make_sync(config, client)
    sync.run()
    client.list_calls.clear()
    client.downloads.clear()
    assert sync.run() == {}
    # depuis la dernière activité (5 mars) moins 30 jours
    assert client.list_calls == [("2026-02-03", "2026-02-28"), ("2026-03-01", "2026-03-10")]
    assert client.downloads == []


def test_rename_delete_and_restore(setup):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-03-01 08:00:00"), garmin_act(2, "2026-03-02 08:00:00")])
    sync, _ = make_sync(config, client)
    sync.run()
    client.activities = [garmin_act(1, "2026-03-01 08:00:00", name="Bastille")]
    assert sync.run() == {"renamed": 1, "deleted": 1}
    r = rows(conn)
    assert r[1]["garmin_name"] == "Bastille" and r[2]["deleted_in_garmin"] == 1
    client.activities.append(garmin_act(2, "2026-03-02 08:00:00"))
    assert sync.run() == {"restored": 1}
    assert rows(conn)[2]["deleted_in_garmin"] == 0


def test_download_error_does_not_stop_sync_and_is_retried_on_full_import(setup):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-01-05 08:00:00"), garmin_act(2, "2026-01-06 08:00:00")])
    client.fail_download["1"] = RuntimeError("404")
    sync, _ = make_sync(config, client)
    assert sync.run() == {"new": 2, "downloaded": 1, "fit_errors": 1}
    r = rows(conn)
    assert r[1]["fit_status"] == "error" and r[1]["fit_error"] == "404"
    # synchro quotidienne : l'erreur n'est pas retentée
    client.downloads.clear()
    sync.run()
    assert client.downloads == []
    # réimport complet : retentée
    del client.fail_download["1"]
    assert sync.run(full_history=True)["downloaded"] == 1
    assert rows(conn)[1]["fit_status"] == "stored" and rows(conn)[1]["fit_error"] is None


def test_non_fit_response_is_an_error(setup):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-01-05 08:00:00")])
    client.download_activity = lambda act_id, dl_fmt=None: b"<html>maintenance</html>"
    sync, _ = make_sync(config, client)
    assert sync.run()["fit_errors"] == 1
    assert not (config.fit_dir / "1.fit").exists()


@pytest.mark.parametrize("exc", [GarminConnectTooManyRequestsError("429"),
                                 GarminConnectAuthenticationError("401")])
def test_fatal_download_error_stops_sync(setup, exc):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-01-05 08:00:00"), garmin_act(2, "2026-01-06 08:00:00")])
    client.fail_download["1"] = exc
    sync, _ = make_sync(config, client)
    with pytest.raises(type(exc)):
        sync.run()
    assert client.downloads == ["1"]
    assert rows(conn)[1]["fit_status"] == "pending"
    run = conn.execute("SELECT * FROM sync_runs").fetchone()
    assert run["status"] == "error" and run["error"]
    assert sync.account.errors == [exc]


def test_login_failure_is_recorded(setup):
    config, conn = setup
    sync, _ = make_sync(config, GarminConnectAuthenticationError("jeton expiré"))
    with pytest.raises(GarminConnectAuthenticationError):
        sync.run()
    run = conn.execute("SELECT * FROM sync_runs").fetchone()
    assert run["status"] == "error" and "jeton expiré" in run["error"]
    assert settings.get_state(conn, "garmin_first_import_done") is None


def test_after_sync_runs_with_progress_and_counts(setup):
    config, conn = setup
    calls = []

    def after(c, progress):
        progress("lecture des FIT", 1, 1, "1")
        calls.append(c.execute("SELECT COUNT(*) FROM activities").fetchone()[0])
        return {"parsed": 1}

    sync = GarminSync(config, FakeAccount(FakeClient([garmin_act(1, "2026-03-05 08:00:00")])),
                      sleep=lambda s: None, today=lambda: date(2026, 3, 10), after_sync=after)
    assert sync.run() == {"new": 1, "downloaded": 1, "parsed": 1}
    assert calls == [1]
    assert "1 FIT lu(s)" in conn.execute("SELECT summary FROM sync_runs").fetchone()[0]


def test_after_sync_failure_is_not_a_garmin_error(setup):
    config, conn = setup

    def after(c, progress):
        raise RuntimeError("disque plein")

    sync = GarminSync(config, FakeAccount(FakeClient([])), sleep=lambda s: None,
                      today=lambda: date(2026, 3, 10), after_sync=after)
    with pytest.raises(RuntimeError):
        sync.run()
    assert sync.account.errors == [] and sync.account.synced == [0]
    run = conn.execute("SELECT * FROM sync_runs").fetchone()
    assert run["status"] == "error" and run["error"] == "disque plein"


def test_concurrent_run_is_refused(setup):
    config, conn = setup
    sync, _ = make_sync(config, FakeClient([]))
    sync._lock.acquire()
    try:
        with pytest.raises(SyncAlreadyRunning):
            sync.run()
    finally:
        sync._lock.release()


# ---------- planificateur ----------

CFG = {"enabled": True, "hour": 4}


def test_is_due():
    assert is_due(datetime(2026, 3, 10, 4, 0), CFG, "2026-03-09")
    assert is_due(datetime(2026, 3, 10, 15, 0), CFG, None)  # rattrapage après redémarrage
    assert not is_due(datetime(2026, 3, 10, 3, 59), CFG, "2026-03-09")
    assert not is_due(datetime(2026, 3, 10, 5, 0), CFG, "2026-03-10")
    assert not is_due(datetime(2026, 3, 10, 5, 0), {**CFG, "enabled": False}, None)


def test_scheduler_runs_once_a_day(setup):
    config, conn = setup
    client = FakeClient([garmin_act(1, "2026-03-05 08:00:00")])
    sync, _ = make_sync(config, client)
    sched = DailyScheduler(config, sync, sync.account)
    assert sched.tick(datetime(2026, 3, 10, 5, 0))
    assert not sched.tick(datetime(2026, 3, 10, 6, 0))
    assert sched.tick(datetime(2026, 3, 11, 4, 0))
    kinds = [r[0] for r in conn.execute("SELECT kind FROM sync_runs")]
    assert kinds == ["garmin-auto", "garmin-auto"]


def test_scheduler_does_not_retry_failed_run_same_day(setup):
    config, conn = setup
    sync, _ = make_sync(config, GarminConnectAuthenticationError("401"))
    sched = DailyScheduler(config, sync, sync.account)
    assert sched.tick(datetime(2026, 3, 10, 5, 0))
    assert not sched.tick(datetime(2026, 3, 10, 5, 1))


# ---------- réglages ----------

def test_settings_validation(setup):
    _, conn = setup
    assert settings.update(conn, "garmin_sync", {"hour": 6})["hour"] == 6
    for bad in [{"hour": 24}, {"hour": True}, {"enabled": "oui"}, {"history_start": "hier"},
                {"history_start": "1990-01-01"}, {"inconnu": 1}]:
        with pytest.raises(ValueError):
            settings.update(conn, "garmin_sync", bad)
    # revenir aux valeurs par défaut efface la ligne
    settings.update(conn, "garmin_sync", {"hour": 4, "history_start": "2015-01-01"})
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key='garmin_sync'").fetchone()[0] == 0
