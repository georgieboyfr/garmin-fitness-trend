"""
Import de l'export de compte Strava : noms des activités, et sorties de course sans
équivalent Garmin (courues sans montre, ou avant la première montre Garmin).

- Fichier déposé dans strava/ (dossier surveillé) ou envoyé depuis l'admin :
  l'archive zip complète, ou seulement activities.csv. Seul le plus récent compte,
  d'après la date de la dernière activité qu'il contient ; un fichier déjà traité
  n'est pas relu.
- activities.csv est exporté dans la langue du compte : en-têtes français ou anglais,
  dates « 7 nov. 2020, 15:54:37 » ou « Nov 7, 2020, 3:54:37 PM », toujours en UTC.
  Certains en-têtes sont en double : la 1re « Distance » est en km (format local),
  la 2e en mètres.
- Appariement avec Garmin par heure de départ UTC, à 2 min près. Les noms génériques
  de Strava (« Course à pied le midi ») ne sont pas repris.
- Une sortie de course sans équivalent Garmin, d'au moins 1 km et avec une trace dans
  l'archive, devient une activité « source Strava » (id = -id Strava). Si Garmin la
  fournit plus tard, la copie Strava est supprimée au profit de l'activité Garmin.
"""
import bisect
import csv
import hashlib
import io
import logging
import os
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("strava")

MATCH_TOLERANCE_S = 120
MIN_IMPORT_DISTANCE_M = 1000.0

HEADERS = {
    "id": ("ID de l'activité", "Activity ID"),
    "date": ("Date de l'activité", "Activity Date"),
    "name": ("Nom de l'activité", "Activity Name"),
    "description": ("Description de l'activité", "Activity Description"),
    "type": ("Type d'activité", "Activity Type"),
    "elapsed": ("Temps écoulé", "Elapsed Time"),
    "distance": ("Distance",),
    "filename": ("Nom du fichier", "Filename"),
    "gain": ("Dénivelé positif", "Elevation Gain"),
}

FR_MONTHS = {"janv.": 1, "févr.": 2, "mars": 3, "avr.": 4, "mai": 5, "juin": 6, "juil.": 7,
             "août": 8, "sept.": 9, "oct.": 10, "nov.": 11, "déc.": 12}
EN_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

RUNNING_TYPES = {
    "Course à pied": "running", "Run": "running",
    "Trail": "trail_running", "Trail Run": "trail_running", "Course sur sentier": "trail_running",
    "Course virtuelle": "virtual_run", "Virtual Run": "virtual_run",
}

_MOMENTS_FR = (r"(le |du |dans l'|de l'|l')?(matin|midi|après-midi|soir)|matinale|en soirée|de nuit|nocturne"
               r"|du soir")
_GENERIC_FR = re.compile(
    r"^(Course à pied|Trail|Natation|Sortie à vélo|Vélo|Marche|Randonnée|Entraînement|Promenade"
    rf"|Séance de musculation|Yoga|Ski|Course virtuelle) ({_MOMENTS_FR})$", re.IGNORECASE)
_GENERIC_EN = re.compile(
    r"^(Morning|Lunch|Afternoon|Evening|Night) (Run|Trail Run|Ride|Walk|Hike|Swim|Workout"
    r"|Weight Training|Yoga|Virtual Run)$", re.IGNORECASE)


@dataclass
class StravaActivity:
    strava_id: int
    start_time_utc: datetime
    name: str
    description: str | None
    activity_type: str
    distance_m: float | None
    elapsed_s: float | None
    elevation_gain_m: float | None
    filename: str | None

    @property
    def generic_name(self) -> bool:
        return is_generic_name(self.name)


def is_generic_name(name: str | None) -> bool:
    name = (name or "").strip()
    return not name or bool(_GENERIC_FR.match(name) or _GENERIC_EN.match(name))


def parse_strava_date(text: str) -> datetime:
    """Date de activities.csv (UTC), en français ou en anglais."""
    text = text.strip()
    m = re.match(r"^(\d{1,2}) (\S+) (\d{4}), (\d{1,2}):(\d{2}):(\d{2})$", text)
    if m and m.group(2) in FR_MONTHS:
        day, month, year, h, mi, s = m.groups()
        return datetime(int(year), FR_MONTHS[month], int(day), int(h), int(mi), int(s), tzinfo=UTC)
    m = re.match(r"^(\w{3}) (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)?$", text)
    if m and m.group(1) in EN_MONTHS:
        month, day, year, h, mi, s, ampm = m.groups()
        h = int(h) % 12 + (12 if ampm == "PM" else 0) if ampm else int(h)
        return datetime(int(year), EN_MONTHS[month], int(day), h, int(mi), int(s), tzinfo=UTC)
    raise ValueError(f"date Strava non reconnue : {text!r}")


def _number(text):
    text = (text or "").strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def read_activities_csv(stream) -> list[StravaActivity]:
    reader = csv.reader(stream)
    header = next(reader)
    positions = {}
    for key, names in HEADERS.items():
        positions[key] = [i for i, h in enumerate(header) if h.strip() in names]
    for key in ("id", "date", "name", "type"):
        if not positions[key]:
            raise ValueError(f"activities.csv : colonne introuvable ({' / '.join(HEADERS[key])})")

    def cell(row, key, occurrence=0):
        pos = positions[key]
        i = pos[occurrence] if len(pos) > occurrence else None
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for row in reader:
        if not row or not cell(row, "id").strip():
            continue
        # 2e colonne « Distance » en mètres ; à défaut la 1re, en km
        meters = _number(cell(row, "distance", 1))
        if meters is None:
            km = _number(cell(row, "distance", 0))
            meters = km * 1000 if km is not None else None
        out.append(StravaActivity(
            strava_id=int(cell(row, "id")),
            start_time_utc=parse_strava_date(cell(row, "date")),
            name=cell(row, "name").strip(),
            description=cell(row, "description").strip() or None,
            activity_type=cell(row, "type").strip(),
            distance_m=meters,
            elapsed_s=_number(cell(row, "elapsed")),
            elevation_gain_m=_number(cell(row, "gain")),
            filename=cell(row, "filename").strip() or None,
        ))
    return out


def read_export(path):
    """(kind, activités, archive zip ouverte ou None) d'un zip d'export ou d'un activities.csv."""
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        names = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == "activities.csv"]
        if not names:
            z.close()
            raise ValueError("archive sans activities.csv")
        with z.open(min(names, key=len)) as f:
            acts = read_activities_csv(io.TextIOWrapper(f, encoding="utf-8-sig"))
        return "zip", acts, z
    with open(path, encoding="utf-8-sig", newline="") as f:
        return "csv", read_activities_csv(f), None


# ---------- traces importées ----------

def trace_path(config, strava_id: int, filename: str) -> Path:
    ext = "".join(Path(filename).suffixes[-2:]) if filename.endswith(".gz") else Path(filename).suffix
    return config.strava_dir / "files" / f"{strava_id}{ext.lower()}"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z"


def _now_iso() -> str:
    return _iso(datetime.now(UTC).replace(microsecond=0))


def _store_rows(conn, acts):
    now = _now_iso()
    with conn:
        for a in acts:
            conn.execute(
                "INSERT INTO strava_activities (strava_id, start_time_utc, name, description, activity_type,"
                " distance_m, elapsed_s, elevation_gain_m, filename, generic_name, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(strava_id) DO UPDATE SET start_time_utc=excluded.start_time_utc,"
                " name=excluded.name, description=excluded.description,"
                " activity_type=excluded.activity_type, distance_m=excluded.distance_m,"
                " elapsed_s=excluded.elapsed_s, elevation_gain_m=excluded.elevation_gain_m,"
                " filename=excluded.filename, generic_name=excluded.generic_name,"
                " updated_at=excluded.updated_at",
                (a.strava_id, _iso(a.start_time_utc), a.name, a.description, a.activity_type,
                 a.distance_m, a.elapsed_s,
                 a.elevation_gain_m, a.filename, int(a.generic_name), now),
            )


def match_all(config, conn, archive=None) -> Counter:
    """Apparie toutes les activités Strava aux activités Garmin, et importe (ou supprime)
    les sorties Strava sans équivalent Garmin. Idempotent."""
    counts = Counter()
    garmin = sorted(
        (datetime.fromisoformat(r[0].rstrip("Z")), r[1]) for r in conn.execute(
            "SELECT start_time_utc, id FROM activities WHERE source = 'garmin' AND deleted_in_garmin = 0")
    )
    times = [g[0] for g in garmin]
    tz = ZoneInfo(config.timezone)
    rows = conn.execute("SELECT * FROM strava_activities ORDER BY start_time_utc").fetchall()
    for s in rows:
        t = datetime.fromisoformat(s["start_time_utc"].rstrip("Z"))
        i = bisect.bisect_left(times, t)
        near = [(abs((times[j] - t).total_seconds()), garmin[j][1])
                for j in (i - 1, i) if 0 <= j < len(times)]
        best = min(near) if near else None
        imported_id = -s["strava_id"]
        with conn:
            if best and best[0] <= MATCH_TOLERANCE_S:
                if s["activity_id"] != best[1]:
                    conn.execute("UPDATE strava_activities SET activity_id=? WHERE strava_id=?",
                                 (best[1], s["strava_id"]))
                    counts["matched_new"] += 1
                # Garmin la fournit désormais : la copie Strava n'a plus lieu d'être
                cur = conn.execute("DELETE FROM activities WHERE id=? AND source='strava'", (imported_id,))
                if cur.rowcount:
                    counts["replaced"] += 1
                counts["matched"] += 1
                continue
            sport = RUNNING_TYPES.get(s["activity_type"])
            if not sport or (s["distance_m"] or 0) < MIN_IMPORT_DISTANCE_M or not s["filename"]:
                if s["activity_id"] is not None and s["activity_id"] != imported_id:
                    conn.execute("UPDATE strava_activities SET activity_id=NULL WHERE strava_id=?",
                                 (s["strava_id"],))
                counts["unmatched"] += 1
                continue
            path = trace_path(config, s["strava_id"], s["filename"])
            if not path.exists():
                if archive is None or s["filename"] not in archive.namelist():
                    counts["missing_trace"] += 1
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".part")
                with archive.open(s["filename"]) as src, open(tmp, "wb") as dst:
                    dst.write(src.read())
                os.replace(tmp, path)
            exists = conn.execute("SELECT 1 FROM activities WHERE id=?", (imported_id,)).fetchone()
            if not exists:
                now = _now_iso()
                conn.execute(
                    "INSERT INTO activities (id, source, start_time_utc, start_time_local, activity_type,"
                    " distance_m, duration_s, fit_status, first_seen_at, updated_at)"
                    " VALUES (?, 'strava', ?, ?, ?, ?, ?, 'stored', ?, ?)",
                    (imported_id, s["start_time_utc"],
                     t.replace(tzinfo=UTC).astimezone(tz).replace(tzinfo=None).isoformat(),
                     sport, s["distance_m"], s["elapsed_s"], now, now),
                )
                counts["imported_new"] += 1
            if s["activity_id"] != imported_id:
                conn.execute("UPDATE strava_activities SET activity_id=? WHERE strava_id=?",
                             (imported_id, s["strava_id"]))
            counts["imported"] += 1
    return counts


# ---------- import d'un fichier ----------

def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _record(conn, path, st, **values):
    with conn:
        conn.execute(
            "INSERT INTO strava_imports (filename, size, mtime, sha256, kind, status, activities,"
            " last_activity_utc, error, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (Path(path).name, st.st_size, st.st_mtime, values.get("sha256"), values.get("kind"),
             values["status"], values.get("activities"), values.get("last_activity_utc"),
             values.get("error"), _now_iso()),
        )


def already_seen(conn, path) -> bool:
    st = os.stat(path)
    return conn.execute("SELECT 1 FROM strava_imports WHERE filename=? AND size=? AND mtime=?",
                        (Path(path).name, st.st_size, st.st_mtime)).fetchone() is not None


def import_file(config, conn, path) -> dict:
    """Traite un fichier d'export. Retourne {status, ...} (voir strava_imports)."""
    st = os.stat(path)
    sha = _sha256(path)
    if conn.execute("SELECT 1 FROM strava_imports WHERE sha256=? AND status='ok'", (sha,)).fetchone():
        _record(conn, path, st, sha256=sha, status="duplicate")
        return {"status": "duplicate"}
    try:
        kind, acts, archive = read_export(path)
    except Exception as e:
        log.warning("Export Strava %s illisible : %s", path, e)
        _record(conn, path, st, sha256=sha, status="error", error=str(e)[:1000])
        return {"status": "error", "error": str(e)}
    try:
        last = max((a.start_time_utc for a in acts), default=None)
        last_iso = _iso(last) if last else None
        newest = conn.execute(
            "SELECT MAX(last_activity_utc) FROM strava_imports WHERE status='ok'").fetchone()[0]
        if newest and last_iso and last_iso < newest:
            log.info("Export Strava %s plus ancien que le dernier importé : ignoré", path)
            _record(conn, path, st, sha256=sha, kind=kind, status="older", activities=len(acts),
                    last_activity_utc=last_iso)
            return {"status": "older", "activities": len(acts)}
        _store_rows(conn, acts)
        counts = match_all(config, conn, archive)
        _record(conn, path, st, sha256=sha, kind=kind, status="ok", activities=len(acts),
                last_activity_utc=last_iso)
        log.info("Export Strava %s importé : %d activités, %s", path, len(acts), dict(counts))
        return {"status": "ok", "activities": len(acts), **counts}
    finally:
        if archive is not None:
            archive.close()


def scan_folder(config, conn) -> list[dict]:
    """Importe les fichiers du dossier surveillé qui n'ont pas encore été vus,
    du plus ancien au plus récent (dépôt)."""
    folder = config.strava_dir
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in (".zip", ".csv") and not p.name.endswith(".part")]
    results = []
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        if not already_seen(conn, p):
            results.append({"file": p.name, **import_file(config, conn, p)})
    return results
