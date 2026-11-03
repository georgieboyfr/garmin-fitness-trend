import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, admin, db, processing
from .auth import AdminAuth, LoginThrottle, load_or_create_secret
from .config import Config, load_config
from .dem import CopernicusDem, Dem, IgnDem
from .garmin_account import GarminAccount
from .garmin_sync import GarminSync
from .scheduler import DailyScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def create_app(config: Config | None = None, garmin_class=None, sync_options=None,
               start_scheduler=True, dem_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        cfg = config or load_config()
        cfg.ensure_dirs()
        conn = db.connect(cfg.db_path)
        try:
            applied = db.migrate(conn)
            log.info("Garmin Fitness Trend %s, base en version %d (%d migration(s) appliquée(s))",
                     __version__, db.schema_version(conn), len(applied))
        finally:
            conn.close()
        app.state.config = cfg
        app.state.auth = AdminAuth(cfg.admin_user, cfg.admin_password_hash,
                                   load_or_create_secret(cfg.session_secret_path))
        app.state.login_throttle = LoginThrottle()
        app.state.garmin_account = GarminAccount(
            cfg.garmin_tokens_dir, cfg.garmin_state_path,
            env_email=cfg.garmin_email, env_password=cfg.garmin_password, garmin_class=garmin_class,
        )
        dem = dem_factory() if dem_factory else Dem(IgnDem(), CopernicusDem(cfg.dem_dir / "copernicus"))
        app.state.garmin_sync = GarminSync(
            cfg, app.state.garmin_account,
            after_sync=lambda conn, progress: processing.run_all(cfg, conn, dem, progress),
            **(sync_options or {}),
        )
        scheduler = DailyScheduler(cfg, app.state.garmin_sync, app.state.garmin_account)
        if start_scheduler:
            scheduler.start()
        if not app.state.auth.enabled:
            log.warning("ADMIN_PASSWORD_HASH non défini : l'administration (/admin) est désactivée.")
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(title="Garmin Fitness Trend", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health():
        try:
            conn = db.connect(app.state.config.db_path)
            try:
                version = db.schema_version(conn)
            finally:
                conn.close()
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=503)
        return {"status": "ok", "version": __version__, "schema_version": version}

    @app.get("/", include_in_schema=False)
    def home():
        # pas encore de pages de statistiques (phase 2) : l'admin est la seule page
        return RedirectResponse("/admin")

    app.include_router(admin.pages)
    app.include_router(admin.public)
    app.include_router(admin.protected)
    app.mount("/static", StaticFiles(directory=admin.STATIC_DIR), name="static")
    return app


app = create_app()
