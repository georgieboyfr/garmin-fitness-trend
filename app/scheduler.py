"""
Synchro Garmin quotidienne et dossier Strava surveillé, dans le conteneur.

Toutes les minutes, le planificateur regarde si la synchro du jour est due : synchro
activée, heure réglée atteinte, pas encore lancée aujourd'hui, compte Garmin
connecté. Un conteneur redémarré après l'heure prévue rattrape donc la synchro du jour.

Chaque semaine, une fois la synchro du jour faite (ou s'il n'y en a pas), la prédiction de chaque
course suivie est enregistrée avec la forme du dimanche soir (tracked.py).
"""
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db, settings, strava, tracked

log = logging.getLogger("scheduler")


def is_due(now_local: datetime, cfg: dict, last_auto_day: str | None) -> bool:
    return (cfg["enabled"] and now_local.hour >= cfg["hour"]
            and last_auto_day != now_local.date().isoformat())


class DailyScheduler:
    def __init__(self, config, sync, account, interval_s=60):
        self.config = config
        self.sync = sync
        self.account = account
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.wait(self.interval_s):
            for job in (self.scan_strava, self.tick, self.weekly):
                try:
                    job()
                except Exception:
                    log.exception("Planificateur : erreur")

    def scan_strava(self) -> list[dict]:
        """Importe un export Strava déposé dans le dossier surveillé, puis lit les traces
        des sorties importées et calcule leur D+ (sans appel à Garmin)."""
        if self.sync.running:
            return []   # la synchro en cours écrit dans la base : on repassera dans une minute
        conn = db.connect(self.config.db_path)
        try:
            results = strava.scan_folder(self.config, conn)
        finally:
            conn.close()
        if any(r["status"] == "ok" for r in results):
            try:
                self.sync.run(kind="strava", local_only=True)
            except Exception:
                pass  # déjà journalisée et enregistrée dans sync_runs
        return results

    def tick(self, now=None) -> bool:
        """Lance la synchro du jour si elle est due. Retourne True si elle a été lancée."""
        now = now or datetime.now(ZoneInfo(self.config.timezone))
        conn = db.connect(self.config.db_path)
        try:
            cfg = settings.get(conn, "garmin_sync")
            if (not is_due(now, cfg, settings.get_state(conn, "garmin_last_auto_day"))
                    or not self.account.is_configured() or self.sync.running):
                return False
            # noté avant de lancer : une synchro en échec n'est pas relancée en boucle
            settings.set_state(conn, "garmin_last_auto_day", now.date().isoformat())
        finally:
            conn.close()
        log.info("Synchro Garmin quotidienne")
        try:
            self.sync.run(kind="garmin-auto")
        except Exception:
            pass  # déjà journalisée et enregistrée dans sync_runs
        return True

    def weekly(self, now=None) -> int:
        """Prédictions de la semaine des courses suivies, une fois par semaine, après la synchro du
        jour (sinon les sorties du dimanche manqueraient). Retourne le nombre enregistré."""
        now = now or datetime.now(ZoneInfo(self.config.timezone))
        week = tracked.week_of(now.date()).isoformat()
        conn = db.connect(self.config.db_path)
        try:
            if settings.get_state(conn, "tracked_last_week") == week or self.sync.running:
                return 0
            cfg = settings.get(conn, "garmin_sync")
            synced = (not cfg["enabled"] or not self.account.is_configured()
                      or settings.get_state(conn, "garmin_last_auto_day") == now.date().isoformat())
            if now.hour < cfg["hour"] or not synced:
                return 0
            done = tracked.record(self.config, conn, now.date())
            settings.set_state(conn, "tracked_last_week", week)
        finally:
            conn.close()
        if done:
            log.info("Courses suivies : %d prédiction(s) de la semaine enregistrée(s)", done)
        return done
