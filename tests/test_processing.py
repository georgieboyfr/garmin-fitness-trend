import pytest

from app import db, processing
from app.series import read_series

from .fit_builder import build_fit

NOW = "2026-03-01T08:00:00Z"


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    yield c
    c.close()


def add_activity(conn, config, act_id, fit_bytes=None, fit_status="stored"):
    conn.execute(
        "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, fit_status,"
        " first_seen_at, updated_at) VALUES (?, ?, ?, 'running', ?, ?, ?)",
        (act_id, f"2026-03-0{act_id}T08:00:00Z", f"2026-03-0{act_id}T09:00:00", fit_status, NOW, NOW),
    )
    conn.commit()
    if fit_bytes is not None:
        (config.fit_dir / f"{act_id}.fit").write_bytes(fit_bytes)


POINTS = [{"t": i, "lat": 45.19, "lon": 5.72, "distance_m": i * 3.0, "altitude_m": 210.0 + i,
           "heart_rate": 140} for i in range(20)]


def series_rows(conn):
    return {r["activity_id"]: dict(r) for r in conn.execute("SELECT * FROM activity_series")}


@pytest.mark.parametrize("workers", [1, 2])
def test_parse_pending(conn, config, workers):
    add_activity(conn, config, 1, build_fit(POINTS, garmin_product=3992))
    add_activity(conn, config, 2, build_fit([{"t": 0, "heart_rate": 120}], garmin_product=2503))
    add_activity(conn, config, 3, b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT\x00")  # FIT tronqué
    add_activity(conn, config, 4, fit_status="pending")  # pas encore de FIT : ignorée
    seen = []
    counts = processing.parse_pending(config, conn, progress=lambda *a: seen.append(a), workers=workers)
    assert counts == {"parsed": 2, "parse_errors": 1}
    assert [a[1] for a in seen] == [1, 2, 3]

    rows = series_rows(conn)
    assert set(rows) == {1, 2, 3}
    assert rows[1]["status"] == "ok" and rows[1]["n_points"] == 20
    assert (rows[1]["has_gps"], rows[1]["has_altitude"], rows[1]["has_hr"]) == (1, 1, 1)
    assert (rows[2]["has_gps"], rows[2]["has_altitude"]) == (0, 0)
    assert rows[3]["status"] == "error" and rows[3]["error"]

    products = dict(conn.execute("SELECT id, garmin_product FROM activities").fetchall())
    assert products == {1: 3992, 2: 2503, 3: None, 4: None}
    assert read_series(config.series_dir, 1).num_rows == 20

    # tout est à jour : rien à relire, l'erreur n'est pas retentée
    assert processing.parse_pending(config, conn, workers=workers) == {}


def test_new_parser_version_rereads_everything(conn, config, monkeypatch):
    add_activity(conn, config, 1, build_fit(POINTS))
    processing.parse_pending(config, conn, workers=1)
    monkeypatch.setattr(processing, "PARSER_VERSION", processing.PARSER_VERSION + 1)
    assert processing.pending_parse(conn) == [1]
    assert processing.parse_pending(config, conn, workers=1) == {"parsed": 1}
    assert series_rows(conn)[1]["parser_version"] == processing.PARSER_VERSION
