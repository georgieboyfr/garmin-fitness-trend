import os
import zipfile
from datetime import UTC, datetime

import pytest

from app import db, processing, strava

from .fit_builder import build_fit

FR_HEADER = ("ID de l'activité,Date de l'activité,Nom de l'activité,Type d'activité,"
             "Description de l'activité,Temps écoulé,Distance,Nom du fichier,Temps écoulé,Distance,"
             "Dénivelé positif\n")
EN_HEADER = ("Activity ID,Activity Date,Activity Name,Activity Type,Activity Description,Elapsed Time,"
             "Distance,Filename,Elapsed Time,Distance,Elevation Gain\n")
NOW = "2026-03-01T08:00:00Z"

GPX = b"""<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"
 xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"><trk><trkseg>
<trkpt lat="45.1900" lon="5.7200"><ele>210</ele><time>2020-11-07T15:54:37Z</time>
 <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>130</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
<trkpt lat="45.1990" lon="5.7200"><ele>260</ele><time>2020-11-07T16:00:37Z</time></trkpt>
<trkpt lat="45.2080" lon="5.7200"><ele>310</ele><time>2020-11-07T16:06:37Z</time></trkpt>
</trkseg></trk></gpx>"""


def row(sid, date, name, type_="Course à pied", desc="", km="4,59", meters="4590.3", file="", gain="13.1"):
    return f'{sid},"{date}","{name}",{type_},"{desc}",1785,"{km}",{file},1785,{meters},{gain}\n'


@pytest.fixture
def conn(config):
    config.ensure_dirs()
    c = db.connect(config.db_path)
    db.migrate(c)
    yield c
    c.close()


def add_garmin(conn, act_id, utc, name="Grenoble Course à pied"):
    conn.execute(
        "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type, garmin_name,"
        " fit_status, first_seen_at, updated_at) VALUES (?, ?, ?, 'running', ?, 'pending', ?, ?)",
        (act_id, utc, utc.rstrip("Z"), name, NOW, NOW))
    conn.commit()


def write_zip(path, csv_text, files=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("activities.csv", csv_text)
        for name, data in (files or {}).items():
            z.writestr(name, data)
    return path


def names(conn):
    rows = conn.execute("SELECT * FROM activity_names")
    return {r["activity_id"]: (r["name"], r["description"]) for r in rows}


# ---------- lecture ----------

def test_dates_fr_and_en():
    assert strava.parse_strava_date("7 nov. 2020, 15:54:37") == datetime(2020, 11, 7, 15, 54, 37, tzinfo=UTC)
    assert strava.parse_strava_date("1 août 2026, 08:05:00") == datetime(2026, 8, 1, 8, 5, tzinfo=UTC)
    assert strava.parse_strava_date("Nov 7, 2020, 3:54:37 PM") == datetime(2020, 11, 7, 15, 54, 37,
                                                                              tzinfo=UTC)
    assert strava.parse_strava_date("Jan 2, 2021, 12:05:00 AM") == datetime(2021, 1, 2, 0, 5, tzinfo=UTC)
    with pytest.raises(ValueError):
        strava.parse_strava_date("2020-11-07")


@pytest.mark.parametrize("name, generic", [
    ("Course à pied le midi", True), ("Course à pied dans l'après-midi", True),
    ("Course à pied l'après-midi", True), ("Course à pied matinale", True), ("Trail le midi", True),
    ("Course à pied du midi", True), ("Natation le matin", True), ("Sortie à vélo le soir", True),
    ("Morning Run", True), ("Lunch Trail Run", True), ("", True),
    ("Bastille du cowork", False), ("Fractionné", False), ("Course à pied avec Paul", False),
])
def test_generic_names(name, generic):
    assert strava.is_generic_name(name) is generic


def test_read_csv_fr_and_en(tmp_path):
    for header in (FR_HEADER, EN_HEADER):
        date = "7 nov. 2020, 15:54:37" if header is FR_HEADER else "Nov 7, 2020, 3:54:37 PM"
        p = tmp_path / "activities.csv"
        p.write_text(header + row(42, date, "Bastille", desc="avec Paul, côtes", file="activities/42.gpx"),
                     encoding="utf-8")
        kind, acts, archive = strava.read_export(p)
        a = acts[0]
        assert kind == "csv" and archive is None
        assert (a.strava_id, a.name, a.description, a.filename) == (42, "Bastille", "avec Paul, côtes",
                                                                    "activities/42.gpx")
        assert a.start_time_utc == datetime(2020, 11, 7, 15, 54, 37, tzinfo=UTC)
        assert a.distance_m == pytest.approx(4590.3)       # 2e colonne Distance, en mètres
        assert a.elevation_gain_m == pytest.approx(13.1) and a.elapsed_s == 1785


def test_distance_falls_back_to_km_column(tmp_path):
    p = tmp_path / "activities.csv"
    p.write_text(FR_HEADER + row(1, "7 nov. 2020, 15:54:37", "x", meters=""), encoding="utf-8")
    assert strava.read_export(p)[1][0].distance_m == pytest.approx(4590)


def test_missing_column_is_an_error(tmp_path):
    p = tmp_path / "activities.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="colonne"):
        strava.read_export(p)


# ---------- import ----------

def test_import_matches_names_and_descriptions(conn, config):
    add_garmin(conn, 101, "2026-10-29T11:20:30Z")                # 74 s d'écart : apparié
    add_garmin(conn, 102, "2026-10-26T11:17:39Z")                # nom générique Strava : nom Garmin gardé
    add_garmin(conn, 103, "2026-10-20T11:00:00Z")                # rien dans Strava
    csv_text = FR_HEADER + row(1, "29 oct. 2026, 11:19:16", "Fractionné", desc="4x5' r=2'") \
        + row(2, "26 oct. 2026, 11:17:39", "Course à pied le midi") \
        + row(3, "21 oct. 2026, 11:00:00", "PPG", type_="Entraînement", km="0", meters="0")
    p = config.strava_dir / "activities.csv"
    p.write_text(csv_text, encoding="utf-8")
    result = strava.import_file(config, conn, p)
    assert result["status"] == "ok" and result["matched"] == 2 and result["unmatched"] == 1
    n = names(conn)
    assert n[101] == ("Fractionné", "4x5' r=2'")
    assert n[102] == ("Grenoble Course à pied", None)
    assert n[103] == ("Grenoble Course à pied", None)


def test_strava_only_run_is_imported_from_archive_then_parsed(conn, config):
    csv_text = FR_HEADER + row(4303015205, "7 nov. 2020, 15:54:37", "Course à pied dans l'après-midi",
                               file="activities/4303015205.gpx") \
        + row(5, "7 juin 2026, 22:00:00", "Passage Fabien", km="0,30", meters="303",
              file="activities/5.gpx") \
        + row(6, "8 juin 2026, 10:00:00", "Rando", type_="Randonnée", file="activities/6.gpx")
    p = write_zip(config.strava_dir / "export.zip", csv_text,
                  {"activities/4303015205.gpx": GPX, "activities/5.gpx": GPX, "activities/6.gpx": GPX})
    result = strava.import_file(config, conn, p)
    assert result["imported_new"] == 1 and result["unmatched"] == 2
    a = conn.execute("SELECT * FROM activities WHERE id = -4303015205").fetchone()
    assert a["source"] == "strava" and a["activity_type"] == "running"
    assert a["start_time_local"] == "2020-11-07T16:54:37"       # heure de Paris
    assert a["distance_m"] == pytest.approx(4590.3)
    assert names(conn)[-4303015205][0] == "Course à pied dans l'après-midi"
    assert (config.strava_dir / "files" / "4303015205.gpx").exists()

    counts = processing.parse_pending(config, conn, workers=1)
    assert counts == {"parsed": 1}
    s = conn.execute("SELECT * FROM activity_series WHERE activity_id = -4303015205").fetchone()
    assert s["status"] == "ok" and s["n_points"] == 3 and s["has_gps"] and s["has_altitude"] and s["has_hr"]


def test_garmin_activity_later_replaces_strava_copy(conn, config):
    csv_text = FR_HEADER + row(77, "7 nov. 2020, 15:54:37", "Course", file="activities/77.gpx")
    p = write_zip(config.strava_dir / "export.zip", csv_text, {"activities/77.gpx": GPX})
    strava.import_file(config, conn, p)
    assert conn.execute("SELECT COUNT(*) FROM activities WHERE id=-77").fetchone()[0] == 1
    add_garmin(conn, 900, "2020-11-07T15:55:00Z")
    counts = strava.match_all(config, conn)
    assert counts["replaced"] == 1
    assert conn.execute("SELECT COUNT(*) FROM activities WHERE id=-77").fetchone()[0] == 0
    assert conn.execute("SELECT activity_id FROM strava_activities").fetchone()[0] == 900


def test_csv_alone_cannot_import_trace(conn, config):
    p = config.strava_dir / "activities.csv"
    p.write_text(FR_HEADER + row(8, "7 nov. 2020, 15:54:37", "Course", file="activities/8.gpx"),
                 encoding="utf-8")
    assert strava.import_file(config, conn, p)["missing_trace"] == 1
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0


def test_older_duplicate_and_seen_files(conn, config):
    new = config.strava_dir / "new.csv"
    new.write_text(FR_HEADER + row(2, "1 févr. 2026, 10:00:00", "Récent"), encoding="utf-8")
    old = config.strava_dir / "old.csv"
    old.write_text(FR_HEADER + row(1, "1 janv. 2026, 10:00:00", "Ancien"), encoding="utf-8")
    os.utime(old, (1_000, 1_000))   # déposé avant
    os.utime(new, (2_000, 2_000))
    results = strava.scan_folder(config, conn)
    assert [(r["file"], r["status"]) for r in results] == [("old.csv", "ok"), ("new.csv", "ok")]
    assert strava.scan_folder(config, conn) == []              # déjà vus
    # un export plus ancien déposé après coup ne remplace rien
    late = config.strava_dir / "late.csv"
    late.write_text(FR_HEADER + row(1, "1 janv. 2026, 10:00:00", "Ancien renommé"), encoding="utf-8")
    assert strava.scan_folder(config, conn)[0]["status"] == "older"
    assert conn.execute("SELECT name FROM strava_activities WHERE strava_id=1").fetchone()[0] == "Ancien"
    # même contenu sous un autre nom
    copy = config.strava_dir / "copie.csv"
    copy.write_bytes(new.read_bytes())
    assert strava.scan_folder(config, conn)[0]["status"] == "duplicate"


def test_unreadable_file_is_recorded(conn, config):
    p = config.strava_dir / "cassé.zip"
    p.write_bytes(b"PK\x03\x04 pas un zip")
    assert strava.scan_folder(config, conn)[0]["status"] == "error"
    assert conn.execute("SELECT status FROM strava_imports").fetchone()[0] == "error"


def test_garmin_sync_ignores_strava_activities(conn, config):
    """La synchro Garmin ne doit ni marquer supprimée ni télécharger une activité Strava."""
    from .test_garmin_sync import FakeClient, garmin_act, make_sync

    csv_text = FR_HEADER + row(77, "5 janv. 2026, 07:00:00", "Course", file="activities/77.gpx")
    archive = write_zip(config.strava_dir / "e.zip", csv_text, {"activities/77.gpx": GPX})
    strava.import_file(config, conn, archive)
    client = FakeClient([garmin_act(1, "2026-01-06 08:00:00")])
    sync, _ = make_sync(config, client)
    sync.run()
    a = conn.execute("SELECT deleted_in_garmin, fit_status FROM activities WHERE id=-77").fetchone()
    assert tuple(a) == (0, "stored")
    assert client.downloads == ["1"]


def test_parse_track_fit_gz(tmp_path):
    import gzip

    from app.track_parser import parse_track
    p = tmp_path / "a.fit.gz"
    p.write_bytes(gzip.compress(build_fit([{"t": 0, "heart_rate": 120}, {"t": 1, "heart_rate": 121}])))
    assert parse_track(p).n_points == 2
    with pytest.raises(ValueError, match="format"):
        parse_track(tmp_path / "a.tcx")
