"""
Garmin Connect -> FIT -> HRSS synchronisation.

Points importants:
- Les FIT sont maintenant conservés dans /data/fit/<activity_id>.fit.
- Une seule synchronisation peut tourner à la fois (verrouillage).
- Chaque activité est commitée immédiatement : un blocage sur un gros FIT
  ne fait plus perdre les activités précédentes.
- Le fichier en cours et l'étape courante sont visibles dans /api/status.
- Les activités sans FC ne sont pas retéléchargées indéfiniment.
- Le parsing ne parcourt que timestamp + heart_rate au lieu de tous les champs.
"""

import io
import os
import logging
import zipfile
import sqlite3
import math
from datetime import datetime, timedelta

from garminconnect import Garmin
from fitparse import FitFile

try:
    import fcntl
except ImportError:  # pragma: no cover - le conteneur est Linux
    fcntl = None

logger = logging.getLogger("garmin_sync")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
TOKEN_DIR = os.path.join(DATA_DIR, "garth_tokens")
FIT_DIR = os.path.join(DATA_DIR, "fit")
DB_PATH = os.path.join(DATA_DIR, "fitness.db")
LOCK_PATH = os.path.join(DATA_DIR, "sync.lock")

HR_MAX = float(os.environ.get("HR_MAX", "190"))
HR_REST = float(os.environ.get("HR_REST", "50"))
LTHR = float(os.environ.get("LTHR", "170"))
SEX = os.environ.get("SEX", "m").lower()
K = 1.92 if SEX.startswith("m") else 1.67


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(FIT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id TEXT PRIMARY KEY,
            start_time TEXT,
            sport TEXT,
            duration_s REAL,
            avg_hr REAL,
            trimp REAL,
            hrss REAL,
            distance_m REAL,
            elevation_gain_m REAL,
            max_hr REAL,
            avg_cadence REAL,
            max_cadence REAL,
            avg_speed_mps REAL,
            max_speed_mps REAL,
            max_altitude_m REAL,
            min_altitude_m REAL,
            hr_zone_1_s REAL DEFAULT 0,
            hr_zone_2_s REAL DEFAULT 0,
            hr_zone_3_s REAL DEFAULT 0,
            hr_zone_4_s REAL DEFAULT 0,
            hr_zone_5_s REAL DEFAULT 0,
            fit_metrics_status TEXT,
            efficiency_factor REAL,
            vam_mh REAL,
            cardiac_drift_pct REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_stress (
            date TEXT PRIMARY KEY,
            total_hrss REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Journal de traitement des activités qui ne peuvent pas produire de HRSS.
    # Cela évite de retélécharger à chaque synchro les activités sans FC.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_sync (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            fit_path TEXT,
            error TEXT,
            updated_at TEXT
        )
    """)

    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(activities)").fetchall()
    }
    if "distance_m" not in existing_cols:
        conn.execute("ALTER TABLE activities ADD COLUMN distance_m REAL")
    if "elevation_gain_m" not in existing_cols:
        conn.execute("ALTER TABLE activities ADD COLUMN elevation_gain_m REAL")
    for col, typ in [("max_hr","REAL"),("avg_cadence","REAL"),("max_cadence","REAL"),("avg_speed_mps","REAL"),("max_speed_mps","REAL"),("max_altitude_m","REAL"),("min_altitude_m","REAL"),("hr_zone_1_s","REAL DEFAULT 0"),("hr_zone_2_s","REAL DEFAULT 0"),("hr_zone_3_s","REAL DEFAULT 0"),("hr_zone_4_s","REAL DEFAULT 0"),("hr_zone_5_s","REAL DEFAULT 0"),("fit_metrics_status","TEXT"),("efficiency_factor","REAL"),("vam_mh","REAL"),("cardiac_drift_pct","REAL")]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE activities ADD COLUMN {col} {typ}")

    conn.commit()
    return conn


def get_state(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value) if value is not None else None),
    )
    conn.commit()


def _set_progress(conn, **values):
    for key, value in values.items():
        set_state(conn, key, value)



def sync_running():
    """Retourne True si le fichier de verrouillage est actuellement détenu."""
    if fcntl is None:
        # Linux/Docker dans notre cas : cette branche est seulement un fallback.
        return False
    if not os.path.exists(LOCK_PATH):
        return False

    fp = None
    try:
        fp = open(LOCK_PATH, "a+")
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            return False
    finally:
        if fp is not None:
            fp.close()

class SyncLock:
    """Empêche le scheduler et le bouton web de lancer deux syncs simultanées."""

    def __init__(self, path):
        self.path = path
        self.fp = None

    def __enter__(self):
        if fcntl is None:
            return self

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fp = open(self.path, "w")
        try:
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.fp.close()
            self.fp = None
            raise RuntimeError("Une autre synchronisation Garmin est déjà en cours.")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fp is not None:
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            self.fp.close()


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

def _prompt_mfa_background():
    raise RuntimeError(
        "Garmin demande un code MFA, mais aucune saisie interactive n'est "
        "possible en tâche de fond. Relance `docker compose run --rm "
        "garmin-fitness-trend python generate_token.py` pour régénérer le jeton."
    )


def _login_with_fallback(client, tokenstore, prompt_mfa_for_fresh_login=None):
    try:
        client.login(tokenstore)
        return
    except FileNotFoundError:
        pass

    if prompt_mfa_for_fresh_login is not None:
        client.prompt_mfa = prompt_mfa_for_fresh_login
    client.login()
    client.garth.dump(tokenstore)


def get_client():
    os.makedirs(TOKEN_DIR, exist_ok=True)
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "GARMIN_EMAIL / GARMIN_PASSWORD absents de la config (.env)."
        )

    client = Garmin(email, password, prompt_mfa=_prompt_mfa_background)
    try:
        _login_with_fallback(client, TOKEN_DIR)
    except AssertionError as e:
        raise RuntimeError(
            "Le login Garmin a 'réussi' mais le profil renvoyé est invalide "
            f"({e}). Vérifie garminconnect/garth et régénère le jeton."
        ) from e
    return client


# ---------------------------------------------------------------------------
# Calcul TRIMP / HRSS
# ---------------------------------------------------------------------------

def one_hour_trimp_at_lthr():
    hrr_lthr = max(0.0, (LTHR - HR_REST) / (HR_MAX - HR_REST))
    return 60 * hrr_lthr * 0.64 * math.exp(K * hrr_lthr)


def compute_trimp_from_records(hr_series):
    trimp = 0.0
    for i in range(1, len(hr_series)):
        t0, hr0 = hr_series[i - 1]
        t1, hr1 = hr_series[i]
        dt_min = (t1 - t0).total_seconds() / 60.0
        if dt_min <= 0 or dt_min > 5:
            continue
        hr_avg = (hr0 + hr1) / 2.0
        hrr = max(0.0, (hr_avg - HR_REST) / (HR_MAX - HR_REST))
        trimp += dt_min * hrr * 0.64 * math.exp(K * hrr)
    return trimp


# ---------------------------------------------------------------------------
# FIT
# ---------------------------------------------------------------------------

def _extract_fit_bytes(raw_bytes):
    """Garmin ORIGINAL est normalement un ZIP contenant le FIT."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            fit_names = [
                name for name in z.namelist()
                if name.lower().endswith(".fit")
            ]
            if not fit_names:
                raise ValueError("ZIP Garmin sans fichier .FIT")
            # Le FIT d'activité est normalement unique.
            return z.read(fit_names[0])
    except zipfile.BadZipFile:
        # Certains appels peuvent déjà renvoyer les octets FIT.
        return raw_bytes


def _is_fit_file(path):
    try:
        with open(path, "rb") as f:
            header = f.read(12)
        return len(header) >= 12 and header[8:12] == b".FIT"
    except OSError:
        return False


def _atomic_write(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def parse_fit_metrics(fit_path):
    """Extrait les métriques FIT de façon robuste.

    Garmin utilise selon les appareils/versions les champs ``speed`` ou
    ``enhanced_speed`` et ``altitude`` ou ``enhanced_altitude``. On accepte
    les deux afin que les métriques restent calculables sur tout l'historique.
    """
    fitfile = FitFile(fit_path)
    hr_series, samples = [], []
    cadences, speeds, altitudes = [], [], []

    def val(record, *names):
        for name in names:
            try:
                value = record.get_value(name)
            except Exception:
                value = None
            if value is not None:
                return value
        return None

    for record in fitfile.get_messages("record"):
        ts = val(record, "timestamp")
        if ts is None:
            continue
        hr = val(record, "heart_rate")
        cad = val(record, "cadence")
        speed = val(record, "enhanced_speed", "speed")
        altitude = val(record, "enhanced_altitude", "altitude")

        h = None
        try:
            if hr is not None and float(hr) > 0:
                h = float(hr)
                hr_series.append((ts, h))
        except (TypeError, ValueError):
            pass

        sp = None
        try:
            if speed is not None and float(speed) >= 0:
                sp = float(speed)
                speeds.append(sp)
        except (TypeError, ValueError):
            pass

        al = None
        try:
            if altitude is not None and math.isfinite(float(altitude)):
                al = float(altitude)
                altitudes.append(al)
        except (TypeError, ValueError):
            pass

        try:
            if cad is not None and float(cad) > 0:
                cadences.append(float(cad))
        except (TypeError, ValueError):
            pass

        samples.append((ts, h, sp, al))

    hr_series.sort(key=lambda x: x[0])
    samples.sort(key=lambda x: x[0])

    zones = [0.0] * 5
    for i in range(1, len(hr_series)):
        t0, h0 = hr_series[i-1]; t1, h1 = hr_series[i]
        dt_s = (t1-t0).total_seconds()
        if dt_s <= 0 or dt_s > 10:
            continue
        h = (h0+h1)/2
        ratio = h / HR_MAX if HR_MAX else 0
        idx = 0 if ratio < .60 else 1 if ratio < .70 else 2 if ratio < .80 else 3 if ratio < .90 else 4
        zones[idx] += dt_s

    # Efficacité : vitesse moyenne en mouvement / FC moyenne.
    paired = [(ts, h, sp) for ts, h, sp, _ in samples
              if h is not None and sp is not None and sp > 0.8 and h >= 80]
    avg_hr_eff = sum(h for _, h, _ in paired) / len(paired) if paired else None
    avg_speed_eff = sum(sp for _, _, sp in paired) / len(paired) if paired else None
    efficiency = (avg_speed_eff * 3.6 / avg_hr_eff) if avg_hr_eff else None

    # VAM : dénivelé positif entre points valides, avec un seuil de 2 m pour
    # ignorer une grande partie du bruit GPS. On ne compte le temps que quand
    # l'activité est en mouvement. Si l'altitude point-par-point est absente,
    # le gain Garmin du résumé est utilisé par l'appelant comme secours.
    vam_gain = 0.0
    active_seconds = 0.0
    prev = None
    for ts, h, sp, al in samples:
        if prev is not None:
            pts, _, psp, pal = prev
            dt_s = (ts - pts).total_seconds()
            if 0 < dt_s <= 10:
                if al is not None and pal is not None:
                    delta = al - pal
                    if delta >= 2.0:
                        vam_gain += delta
                if (sp is not None and sp > 0.8) or (psp is not None and psp > 0.8):
                    active_seconds += dt_s
        prev = (ts, h, sp, al)
    vam = (vam_gain / active_seconds * 3600) if active_seconds > 60 and vam_gain > 0 else None

    # Dérive cardiaque : évolution de l'efficacité vitesse/FC entre les deux
    # moitiés. On exige une durée et un nombre de points suffisants.
    drift = None
    if len(paired) >= 20:
        mid_ts = paired[0][0] + (paired[-1][0] - paired[0][0]) / 2
        first = [(h, sp) for ts, h, sp in paired if ts <= mid_ts]
        second = [(h, sp) for ts, h, sp in paired if ts > mid_ts]
        if len(first) >= 10 and len(second) >= 10:
            ef1 = (sum(sp for h, sp in first) / len(first) * 3.6) / (sum(h for h, sp in first) / len(first))
            ef2 = (sum(sp for h, sp in second) / len(second) * 3.6) / (sum(h for h, sp in second) / len(second))
            if ef1 > 0:
                drift = (ef2 / ef1 - 1.0) * 100.0

    return {
        "hr_series": hr_series,
        "max_hr": max((h for _, h in hr_series), default=None),
        "avg_cadence": sum(cadences)/len(cadences) if cadences else None,
        "max_cadence": max(cadences) if cadences else None,
        "avg_speed_mps": sum(speeds)/len(speeds) if speeds else None,
        "max_speed_mps": max(speeds) if speeds else None,
        "max_altitude_m": max(altitudes) if altitudes else None,
        "min_altitude_m": min(altitudes) if altitudes else None,
        "zones": zones,
        "efficiency_factor": efficiency,
        "vam_mh": vam,
        "cardiac_drift_pct": drift,
    }

def rebuild_fit_metrics():
    """Recalcule les métriques de performance pour TOUS les FIT déjà stockés.

    Cette fonction est volontairement indépendante de Garmin : elle permet de
    réparer/enrichir un historique ancien sans retélécharger les activités.
    """
    # Utilise exactement le même verrou que la synchronisation Garmin.
    with SyncLock(LOCK_PATH):
        return _rebuild_fit_metrics_locked()

def _rebuild_fit_metrics_locked():
    conn = get_db()
    files = []
    try:
        set_state(conn, "last_sync_status", "running")
        set_state(conn, "last_sync_started", datetime.utcnow().isoformat())
        set_state(conn, "last_sync_error", "")
        for name in os.listdir(FIT_DIR):
            if name.lower().endswith(".fit"):
                files.append(os.path.join(FIT_DIR, name))
        files.sort()
        done = 0
        errors = 0
        total = len(files)
        set_state(conn, "sync_current_stage", "recalcul des métriques FIT")
        for index, path in enumerate(files, 1):
            act_id = os.path.splitext(os.path.basename(path))[0]
            set_state(conn, "sync_current_activity", act_id)
            set_state(conn, "sync_current_index", f"{index}/{total}")
            set_state(conn, "sync_current_fit", path)
            try:
                metrics = parse_fit_metrics(path)
                base = conn.execute(
                    "SELECT elevation_gain_m, duration_s, distance_m, avg_hr FROM activities WHERE id=?",
                    (act_id,),
                ).fetchone()
                if base:
                    elev, duration, distance, avg_hr = base
                    if metrics["vam_mh"] is None and (elev or 0) > 0 and (duration or 0) > 60:
                        metrics["vam_mh"] = float(elev) / float(duration) * 3600.0
                    if metrics["efficiency_factor"] is None and (distance or 0) > 1000 and (duration or 0) > 60 and (avg_hr or 0) > 0:
                        metrics["efficiency_factor"] = (float(distance) / float(duration) * 3.6) / float(avg_hr)
                    status = "done" if metrics["hr_series"] else "no_hr"
                    conn.execute(
                        "UPDATE activities SET max_hr=?,avg_cadence=?,max_cadence=?,avg_speed_mps=?,max_speed_mps=?,max_altitude_m=?,min_altitude_m=?,hr_zone_1_s=?,hr_zone_2_s=?,hr_zone_3_s=?,hr_zone_4_s=?,hr_zone_5_s=?,fit_metrics_status=?,efficiency_factor=?,vam_mh=?,cardiac_drift_pct=? WHERE id=?",
                        (metrics["max_hr"], metrics["avg_cadence"], metrics["max_cadence"], metrics["avg_speed_mps"], metrics["max_speed_mps"], metrics["max_altitude_m"], metrics["min_altitude_m"], *metrics["zones"], status, metrics["efficiency_factor"], metrics["vam_mh"], metrics["cardiac_drift_pct"], act_id),
                    )
                    conn.commit()
                    done += 1
            except Exception as exc:
                errors += 1
                logger.exception("Recalcul métriques %s échoué: %s", act_id, exc)
        summary = f"{done} FIT recalculé(s), {errors} erreur(s)"
        set_state(conn, "last_sync_status", "ok")
        set_state(conn, "last_sync_finished", datetime.utcnow().isoformat())
        set_state(conn, "last_sync_summary", summary)
        set_state(conn, "sync_current_stage", "recalcul terminé")
        set_state(conn, "sync_current_activity", "")
        set_state(conn, "sync_current_fit", "")
        return {"files": total, "updated": done, "errors": errors}
    except Exception as exc:
        set_state(conn, "last_sync_status", "error")
        set_state(conn, "last_sync_error", str(exc)[:2000])
        set_state(conn, "sync_current_stage", "erreur")
        raise
    finally:
        conn.close()

def parse_fit_hr_series(fit_path):
    return parse_fit_metrics(fit_path)["hr_series"]


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------

def _activity_sync_status(conn, act_id):
    row = conn.execute(
        "SELECT status, fit_path FROM activity_sync WHERE id=?", (act_id,)
    ).fetchone()
    return row if row else None


def _record_sync_status(conn, act_id, status, fit_path=None, error=None):
    conn.execute(
        "INSERT INTO activity_sync(id,status,fit_path,error,updated_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "status=excluded.status, fit_path=excluded.fit_path, "
        "error=excluded.error, updated_at=excluded.updated_at",
        (
            act_id,
            status,
            fit_path,
            error,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()


def sync(days_back=30):
    # Le verrou est pris avant même de se connecter à Garmin.
    with SyncLock(LOCK_PATH):
        return _sync_locked(days_back)


def _sync_locked(days_back):
    conn = get_db()
    started = datetime.utcnow().isoformat()
    set_state(conn, "last_sync_status", "running")
    set_state(conn, "last_sync_started", started)
    set_state(conn, "last_sync_error", "")
    set_state(conn, "sync_current_activity", "")
    set_state(conn, "sync_current_stage", "authentification")

    try:
        client = get_client()

        start = (datetime.utcnow() - timedelta(days=days_back)).date()
        end = datetime.utcnow().date()

        set_state(conn, "sync_current_stage", "récupération de la liste Garmin")
        activities = client.get_activities_by_date(
            start.isoformat(), end.isoformat()
        )
        logger.info(
            "%d activité(s) trouvée(s) entre %s et %s",
            len(activities), start, end
        )

        one_hour_trimp = one_hour_trimp_at_lthr()
        new_count = 0
        skipped_no_hr = 0
        failed = 0

        total = len(activities)

        for index, act in enumerate(activities, 1):
            act_id = str(act.get("activityId"))
            if not act_id:
                failed += 1
                continue

            existing = conn.execute(
                "SELECT fit_metrics_status, efficiency_factor, vam_mh, cardiac_drift_pct FROM activities WHERE id=?", (act_id,)
            ).fetchone()
            if existing:
                # Les anciennes activités ont déjà leur FIT mais pas forcément
                # les nouvelles métriques. On les enrichit une seule fois, sans
                # refaire de téléchargement ni de calcul HRSS.
                if existing[0] in ("done", "no_hr") and all(v is not None for v in existing[1:]):
                    continue
                if existing[0] == "error" and all(v is not None for v in existing[1:]):
                    continue
                fit_path_existing = os.path.join(FIT_DIR, f"{act_id}.fit")
                if not _is_fit_file(fit_path_existing):
                    continue
                _set_progress(conn, sync_current_activity=act_id, sync_current_index=f"{index}/{total}", sync_current_stage="enrichissement du FIT", sync_current_fit=fit_path_existing)
                try:
                    metrics = parse_fit_metrics(fit_path_existing)
                    # Secours pour les FIT anciens dépourvus d'altitude point-par-point.
                    if metrics["vam_mh"] is None:
                        base = conn.execute("SELECT elevation_gain_m, duration_s, distance_m FROM activities WHERE id=?", (act_id,)).fetchone()
                        if base and (base[0] or 0) > 0 and (base[1] or 0) > 60:
                            metrics["vam_mh"] = float(base[0]) / float(base[1]) * 3600.0
                    if metrics["efficiency_factor"] is None:
                        base = conn.execute("SELECT distance_m, duration_s, avg_hr FROM activities WHERE id=?", (act_id,)).fetchone()
                        if base and (base[0] or 0) > 1000 and (base[1] or 0) > 60 and (base[2] or 0) > 0:
                            metrics["efficiency_factor"] = ((float(base[0]) / float(base[1])) * 3.6) / float(base[2])
                    status = "done" if metrics["hr_series"] else "no_hr"
                    conn.execute(
                        "UPDATE activities SET max_hr=?,avg_cadence=?,max_cadence=?,avg_speed_mps=?,max_speed_mps=?,max_altitude_m=?,min_altitude_m=?,hr_zone_1_s=?,hr_zone_2_s=?,hr_zone_3_s=?,hr_zone_4_s=?,hr_zone_5_s=?,fit_metrics_status=?,efficiency_factor=?,vam_mh=?,cardiac_drift_pct=? WHERE id=?",
                        (metrics["max_hr"], metrics["avg_cadence"], metrics["max_cadence"], metrics["avg_speed_mps"], metrics["max_speed_mps"], metrics["max_altitude_m"], metrics["min_altitude_m"], *metrics["zones"], status, metrics["efficiency_factor"], metrics["vam_mh"], metrics["cardiac_drift_pct"], act_id)
                    )
                    conn.commit()
                    logger.info("[%d/%d] activité %s enrichie", index, total, act_id)
                except Exception as e:
                    logger.exception("[%d/%d] enrichissement %s échoué : %s", index, total, act_id, e)
                continue

            sync_status = _activity_sync_status(conn, act_id)
            if sync_status and sync_status[0] == "no_hr":
                skipped_no_hr += 1
                continue

            fit_path = os.path.join(FIT_DIR, f"{act_id}.fit")
            _set_progress(
                conn,
                sync_current_activity=act_id,
                sync_current_index=f"{index}/{total}",
                sync_current_stage="préparation du FIT",
                sync_current_fit=fit_path,
            )

            logger.info(
                "[%d/%d] activité %s : début (date=%s, durée=%ss, FC moyenne=%s)",
                index, total, act_id,
                act.get("startTimeLocal"),
                act.get("duration"),
                act.get("averageHR"),
            )

            try:
                # Si le FIT existe déjà (interruption précédente), on le réutilise.
                if not _is_fit_file(fit_path):
                    set_state(conn, "sync_current_stage", "téléchargement FIT")
                    logger.info("[%s] téléchargement FIT...", act_id)
                    raw = client.download_activity(
                        act_id,
                        dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
                    )
                    fit_bytes = _extract_fit_bytes(raw)
                    if len(fit_bytes) < 12 or fit_bytes[8:12] != b".FIT":
                        raise ValueError(
                            f"Réponse Garmin non FIT ({len(fit_bytes)} octets)"
                        )
                    _atomic_write(fit_path, fit_bytes)
                    logger.info(
                        "[%s] FIT écrit : %.1f Ko",
                        act_id, len(fit_bytes) / 1024,
                    )
                else:
                    logger.info("[%s] FIT déjà présent : %s", act_id, fit_path)

                set_state(conn, "sync_current_stage", "parsing FIT")
                logger.info("[%s] parsing FIT...", act_id)
                fit_metrics = parse_fit_metrics(fit_path)
                hr_series = fit_metrics["hr_series"]
                # Secours si le FIT ne contient pas les champs GPS nécessaires.
                if fit_metrics["vam_mh"] is None and (act.get("elevationGain") or 0) > 0 and (act.get("duration") or 0) > 60:
                    fit_metrics["vam_mh"] = float(act["elevationGain"]) / float(act["duration"]) * 3600.0
                if fit_metrics["efficiency_factor"] is None and (act.get("distance") or 0) > 1000 and (act.get("duration") or 0) > 60 and (act.get("averageHR") or 0) > 0:
                    fit_metrics["efficiency_factor"] = (float(act["distance"]) / float(act["duration"]) * 3.6) / float(act["averageHR"])
                logger.info(
                    "[%s] parsing terminé : %d échantillons FC",
                    act_id, len(hr_series),
                )

                if not hr_series:
                    # IMPORTANT : on mémorise l'absence de FC pour ne pas
                    # retélécharger ce fichier à chaque synchronisation.
                    _record_sync_status(
                        conn, act_id, "no_hr", fit_path=fit_path,
                        error="Aucun échantillon heart_rate dans le FIT"
                    )
                    skipped_no_hr += 1
                    continue

                trimp = compute_trimp_from_records(hr_series)
                hrss = (trimp / one_hour_trimp) * 100.0 if one_hour_trimp else 0.0

                start_time = (
                    act.get("startTimeLocal")
                    or hr_series[0][0].isoformat()
                )

                conn.execute(
                    "INSERT INTO activities "
                    "(id,start_time,sport,duration_s,avg_hr,trimp,hrss,"
                    "distance_m,elevation_gain_m,max_hr,avg_cadence,max_cadence,avg_speed_mps,max_speed_mps,max_altitude_m,min_altitude_m,hr_zone_1_s,hr_zone_2_s,hr_zone_3_s,hr_zone_4_s,hr_zone_5_s,fit_metrics_status,efficiency_factor,vam_mh,cardiac_drift_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        act_id,
                        start_time,
                        (act.get("activityType") or {}).get(
                            "typeKey", "unknown"
                        ),
                        act.get("duration", 0),
                        act.get("averageHR"),
                        trimp,
                        hrss,
                        act.get("distance"),
                        act.get("elevationGain"),
                        fit_metrics["max_hr"], fit_metrics["avg_cadence"], fit_metrics["max_cadence"],
                        fit_metrics["avg_speed_mps"], fit_metrics["max_speed_mps"], fit_metrics["max_altitude_m"], fit_metrics["min_altitude_m"],
                        *fit_metrics["zones"],
                        "done", fit_metrics["efficiency_factor"], fit_metrics["vam_mh"], fit_metrics["cardiac_drift_pct"],
                    ),
                )

                day = str(start_time)[:10]
                row = conn.execute(
                    "SELECT total_hrss FROM daily_stress WHERE date=?",
                    (day,),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE daily_stress SET total_hrss=? WHERE date=?",
                        (row[0] + hrss, day),
                    )
                else:
                    conn.execute(
                        "INSERT INTO daily_stress(date,total_hrss) VALUES(?,?)",
                        (day, hrss),
                    )

                _record_sync_status(
                    conn, act_id, "done", fit_path=fit_path
                )

                # COMMIT IMMÉDIAT :
                # si l'activité suivante bloque, celle-ci reste en base.
                conn.commit()
                new_count += 1

                logger.info(
                    "[%d/%d] activité %s OK : HRSS=%.1f",
                    index, total, act_id, hrss,
                )

            except Exception as e:
                failed += 1
                logger.exception(
                    "[%d/%d] activité %s échouée : %s",
                    index, total, act_id, e,
                )
                _record_sync_status(
                    conn, act_id, "error", fit_path=fit_path,
                    error=str(e)[:1000]
                )
                # On continue avec l'activité suivante au lieu de tuer toute
                # la synchronisation.
                continue

        summary = (
            f"{new_count} nouvelle(s) activité(s), "
            f"{skipped_no_hr} sans FC, {failed} échec(s)"
        )
        set_state(conn, "last_sync_status", "ok")
        set_state(conn, "last_sync_finished", datetime.utcnow().isoformat())
        set_state(conn, "last_sync_summary", summary)
        set_state(conn, "sync_current_stage", "terminée")
        set_state(conn, "sync_current_activity", "")

        logger.info("Sync terminée : %s", summary)
        return new_count

    except Exception as e:
        logger.exception("Synchronisation échouée : %s", e)
        set_state(conn, "last_sync_status", "error")
        set_state(conn, "last_sync_error", str(e)[:2000])
        set_state(conn, "sync_current_stage", "erreur")
        raise
    finally:
        conn.close()
