import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import __version__, db
from .config import Config, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def create_app(config: Config | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        cfg = config or load_config()
        cfg.ensure_dirs()
        conn = db.connect(cfg.db_path)
        applied = db.migrate(conn)
        log.info("Garmin Fitness Trend %s, base en version %d (%d migration(s) appliquée(s))",
                 __version__, db.schema_version(conn), len(applied))
        app.state.config = cfg
        app.state.db = conn
        try:
            yield
        finally:
            conn.close()

    app = FastAPI(title="Garmin Fitness Trend", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health():
        try:
            version = db.schema_version(app.state.db)
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=503)
        return {"status": "ok", "version": __version__, "schema_version": version}

    return app


app = create_app()
