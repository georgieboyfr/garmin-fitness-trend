"""
Synchronisation Garmin Connect -> base + FIT.

Deux temps, chacun idempotent et relançable sans risque :

1. Liste des activités (get_activities_by_date), mois par mois. Les métadonnées sont
   insérées ou mises à jour (renommages), et les activités connues qui ont disparu de
   la liste sont marquées supprimées dans Garmin (réversible si elles réapparaissent).
   - premier import, ou réimport demandé dans l'admin : depuis history_start ;
   - ensuite : depuis la dernière activité connue moins 30 jours, pour capter les
     renommages et suppressions récents, et rattraper une éventuelle coupure.
2. FIT original de chaque activité qui n'en a pas encore, stocké tel quel dans
   fit/<id>.fit et jamais retéléchargé. Un FIT déjà présent (ancienne application,
   synchro interrompue) est repris sans appel à Garmin.

Des pauses entre les appels ménagent l'API non officielle de Garmin.
"""
import io
import logging
import os
import threading
import time
import zipfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, settings
from .garmin_account import GarminNotConnected, MfaRequired, _is_auth_error

log = logging.getLogger("garmin_sync")

RECENT_WINDOW_DAYS = 30
LIST_DELAY_S = 2.0
DOWNLOAD_DELAY_S = 1.0


class SyncAlreadyRunning(RuntimeError):
    pass


# ---------- conversions ----------

def _parse_garmin_dt(value) -> datetime:
    # Garmin renvoie "2026-01-20 11:14:54" (parfois avec un T ou des fractions de seconde)
    return datetime.strptime(str(value).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")


def parse_activity(act: dict) -> dict | None:
    """Métadonnées d'une activité de la liste Garmin, ou None si elle est inexploitable."""
    try:
        act_id = int(act["activityId"])
        utc = _parse_garmin_dt(act["startTimeGMT"])
        local = _parse_garmin_dt(act["startTimeLocal"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "id": act_id,
        "start_time_utc": utc.isoformat() + "Z",
        "start_time_local": local.isoformat(),
        "activity_type": (act.get("activityType") or {}).get("typeKey") or "unknown",
        "garmin_name": act.get("activityName"),
        "distance_m": act.get("distance"),
        "duration_s": act.get("duration"),
        "moving_duration_s": act.get("movingDuration"),
        "avg_hr": act.get("averageHR"),
        "max_hr": act.get("maxHR"),
        "garmin_elevation_gain_m": act.get("elevationGain"),
    }


def month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Découpe [start, end] en tranches d'un mois civil au plus (bornes incluses)."""
    ranges = []
    a = start
    while a <= end:
        next_month = date(a.year + (a.month == 12), a.month % 12 + 1, 1)
        b = min(next_month - timedelta(days=1), end)
        ranges.append((a, b))
        a = next_month
    return ranges


# ---------- fichiers FIT ----------

def _has_fit_header(data: bytes) -> bool:
    return len(data) >= 12 and data[8:12] == b".FIT"


def extract_fit(raw: bytes) -> bytes:
    """Le téléchargement ORIGINAL de Garmin est un zip contenant le FIT."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".fit")]
            if not names:
                raise ValueError("archive Garmin sans fichier .fit")
            raw = z.read(names[0])
    if not _has_fit_header(raw):
        raise ValueError(f"réponse Garmin qui n'est pas un FIT ({len(raw)} octets)")
    return raw


def is_fit_file(path) -> bool:
    try:
        with open(path, "rb") as f:
            return _has_fit_header(f.read(12))
    except OSError:
        return False


def atomic_write(path, data: bytes):
    tmp = f"{path}.part"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _is_fatal(exc) -> bool:
    """Erreurs qui doivent arrêter la synchro au lieu de passer à l'activité suivante."""
    return (_is_auth_error(exc) or isinstance(exc, GarminNotConnected | MfaRequired)
            or "TooManyRequests" in exc.__class__.__name__)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def summary_text(counts) -> str:
    parts = [
        ("new", "nouvelle(s) activité(s)"), ("renamed", "renommée(s)"),
        ("deleted", "supprimée(s) dans Garmin"), ("restored", "réapparue(s)"),
        ("downloaded", "FIT téléchargé(s)"), ("reused", "FIT repris du disque"),
        ("fit_errors", "FIT en erreur"), ("parsed", "FIT lu(s)"), ("parse_errors", "FIT illisible(s)"),
        ("elevation", "D+ calculé(s)"), ("elevation_postponed", "D+ reporté(s) (MNT indisponible)"),
    ]
    text = ", ".join(f"{counts[k]} {label}" for k, label in parts if counts.get(k))
    return text or "rien de nouveau"


# ---------- synchro ----------

class GarminSync:
    def __init__(self, config, account, sleep=time.sleep, today=None,
                 list_delay=LIST_DELAY_S, download_delay=DOWNLOAD_DELAY_S, after_sync=None):
        self.config = config
        self.account = account
        # after_sync(conn, progress) -> Counter : traitements locaux enchaînés après la synchro
        self.after_sync = after_sync
        self.sleep = sleep
        self.today = today or (lambda: datetime.now(ZoneInfo(config.timezone)).date())
        self.list_delay = list_delay
        self.download_delay = download_delay
        self._lock = threading.Lock()
        self.progress = {}

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def run(self, full_history=False, kind="garmin", local_only=False) -> dict:
        """Lance une synchro (bloquant). Retourne les compteurs.

        local_only : seulement les traitements locaux (recalcul après un changement de
        réglage), sans appel à Garmin, sous le même verrou que la synchro."""
        if not self._lock.acquire(blocking=False):
            raise SyncAlreadyRunning("Une synchronisation Garmin est déjà en cours.")
        try:
            conn = db.connect(self.config.db_path)
            try:
                return self._run(conn, full_history, kind, local_only)
            finally:
                conn.close()
        finally:
            self.progress = {}
            self._lock.release()

    def _set_progress(self, stage, index=None, total=None, detail=None):
        self.progress = {"stage": stage, "index": index, "total": total, "detail": detail}

    @staticmethod
    def _fail_run(conn, run_id, counts, exc):
        with conn:
            conn.execute(
                "UPDATE sync_runs SET finished_at=?, status='error', summary=?, error=? WHERE id=?",
                (_now_iso(), summary_text(counts), str(exc)[:2000] or exc.__class__.__name__, run_id),
            )

    def _run(self, conn, full_history, kind, local_only=False):
        with conn:
            run_id = conn.execute(
                "INSERT INTO sync_runs (kind, started_at, status) VALUES (?, ?, 'running')",
                (kind, _now_iso()),
            ).lastrowid
        counts = Counter()
        if not local_only:
            self._garmin_part(conn, run_id, full_history, counts)
        # traitements locaux (lecture des FIT, D+...), sans appel à Garmin
        if self.after_sync:
            try:
                counts.update(self.after_sync(conn, self._set_progress))
            except Exception as e:
                log.exception("Traitements après la synchro échoués")
                self._fail_run(conn, run_id, counts, e)
                raise
        text = summary_text(counts)
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?, status='ok', summary=? WHERE id=?",
                         (_now_iso(), text, run_id))
        log.info("%s terminée : %s", "Recalcul" if local_only else "Synchro Garmin", text)
        return dict(counts)

    def _garmin_part(self, conn, run_id, full_history, counts):
        try:
            self._set_progress("connexion à Garmin")
            client = self.account.client()
            first = full_history or not settings.get_state(conn, "garmin_first_import_done", False)
            ranges = self._ranges(conn, first)
            log.info("Synchro Garmin (%s) : %d mois à lister, du %s au %s",
                     "import complet" if first else "incrémentale", len(ranges), ranges[0][0], ranges[-1][1])
            for i, (a, b) in enumerate(ranges, 1):
                self._set_progress("liste des activités", i, len(ranges), a.strftime("%m/%Y"))
                acts = client.get_activities_by_date(a.isoformat(), b.isoformat()) or []
                self._store_listing(conn, a, b, acts, counts)
                if i < len(ranges):
                    self.sleep(self.list_delay)
            if first:
                settings.set_state(conn, "garmin_first_import_done", True)
            # les FIT en erreur (activités manuelles sans fichier...) ne sont retentés
            # qu'au réimport complet, pour ne pas solliciter Garmin chaque jour pour rien
            self._fetch_fits(conn, client, counts, retry_errors=full_history)
        except Exception as e:
            log.exception("Synchro Garmin échouée")
            self.account.record_error(e)
            self.account.invalidate()
            self._fail_run(conn, run_id, counts, e)
            raise
        self.account.record_sync(counts["downloaded"])

    def _ranges(self, conn, first):
        today = self.today()
        if first:
            start = date.fromisoformat(settings.get(conn, "garmin_sync")["history_start"])
        else:
            last = conn.execute(
                "SELECT MAX(start_time_local) FROM activities WHERE deleted_in_garmin=0 AND source='garmin'"
            ).fetchone()[0]
            start = (date.fromisoformat(last[:10]) if last else today) - timedelta(days=RECENT_WINDOW_DAYS)
        return month_ranges(min(start, today), today)

    def _store_listing(self, conn, a: date, b: date, acts, counts):
        now = _now_iso()
        seen = set()
        with conn:
            for act in acts:
                row = parse_activity(act)
                if row is None:
                    counts["ignored"] += 1
                    continue
                seen.add(row["id"])
                old = conn.execute("SELECT garmin_name, deleted_in_garmin FROM activities WHERE id=?",
                                   (row["id"],)).fetchone()
                if old is None:
                    counts["new"] += 1
                else:
                    if old["garmin_name"] != row["garmin_name"]:
                        counts["renamed"] += 1
                    if old["deleted_in_garmin"]:
                        counts["restored"] += 1
                conn.execute(
                    "INSERT INTO activities (id, start_time_utc, start_time_local, activity_type,"
                    " garmin_name, distance_m, duration_s, moving_duration_s, avg_hr, max_hr,"
                    " garmin_elevation_gain_m,"
                    " first_seen_at, updated_at)"
                    " VALUES (:id, :start_time_utc, :start_time_local, :activity_type, :garmin_name,"
                    " :distance_m, :duration_s, :moving_duration_s, :avg_hr, :max_hr,"
                    " :garmin_elevation_gain_m,"
                    " :now, :now)"
                    " ON CONFLICT(id) DO UPDATE SET start_time_utc=excluded.start_time_utc,"
                    " start_time_local=excluded.start_time_local, activity_type=excluded.activity_type,"
                    " garmin_name=excluded.garmin_name, distance_m=excluded.distance_m,"
                    " duration_s=excluded.duration_s, moving_duration_s=excluded.moving_duration_s,"
                    " avg_hr=excluded.avg_hr, max_hr=excluded.max_hr,"
                    " garmin_elevation_gain_m=excluded.garmin_elevation_gain_m, deleted_in_garmin=0,"
                    " updated_at=excluded.updated_at",
                    {**row, "now": now},
                )
            # activités connues de la période qui n'apparaissent plus dans Garmin
            known = conn.execute(
                "SELECT id FROM activities WHERE deleted_in_garmin=0 AND source='garmin'"
                " AND substr(start_time_local, 1, 10) BETWEEN ? AND ?",
                (a.isoformat(), b.isoformat()),
            ).fetchall()
            for (act_id,) in known:
                if act_id not in seen:
                    conn.execute("UPDATE activities SET deleted_in_garmin=1, updated_at=? WHERE id=?",
                                 (now, act_id))
                    counts["deleted"] += 1

    def _fetch_fits(self, conn, client, counts, retry_errors=False):
        from garminconnect import Garmin

        statuses = ("pending", "error") if retry_errors else ("pending",)
        rows = conn.execute(
            f"SELECT id FROM activities WHERE deleted_in_garmin=0 AND source='garmin'"
            f" AND fit_status IN ({','.join('?' * len(statuses))}) ORDER BY start_time_utc",
            statuses,
        ).fetchall()
        for i, (act_id,) in enumerate(rows, 1):
            self._set_progress("fichiers FIT", i, len(rows), str(act_id))
            path = self.config.fit_dir / f"{act_id}.fit"
            if is_fit_file(path):
                self._mark_fit(conn, act_id, "stored")
                counts["reused"] += 1
                continue
            try:
                raw = client.download_activity(str(act_id), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
                atomic_write(path, extract_fit(raw))
                self._mark_fit(conn, act_id, "stored")
                counts["downloaded"] += 1
                log.info("[%d/%d] FIT %s téléchargé", i, len(rows), act_id)
            except Exception as e:
                if _is_fatal(e):
                    raise
                log.warning("[%d/%d] FIT %s en erreur : %s", i, len(rows), act_id, e)
                self._mark_fit(conn, act_id, "error", str(e)[:1000] or e.__class__.__name__)
                counts["fit_errors"] += 1
            if i < len(rows):
                self.sleep(self.download_delay)

    @staticmethod
    def _mark_fit(conn, act_id, status, error=None):
        with conn:
            conn.execute("UPDATE activities SET fit_status=?, fit_error=?, updated_at=? WHERE id=?",
                         (status, error, _now_iso(), act_id))
