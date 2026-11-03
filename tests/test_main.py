from fastapi.testclient import TestClient

from app import __version__, db
from app.main import create_app


def test_health_after_startup(config):
    with TestClient(create_app(config)) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__,
                        "schema_version": len(db.load_migrations())}
    assert config.db_path.exists()
    assert config.fit_dir.is_dir()


def test_home_redirects_to_admin(config):
    with TestClient(create_app(config, start_scheduler=False)) as client:
        r = client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/admin"
