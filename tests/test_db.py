import sqlite3

import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def write(directory, name, sql):
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(sql, encoding="utf-8")


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_real_migrations_apply_and_are_idempotent(conn):
    applied = db.migrate(conn)
    assert applied[0] == "0001_initial.sql"
    assert db.schema_version(conn) == len(db.load_migrations())
    assert db.migrate(conn) == []


def test_initial_schema(conn):
    db.migrate(conn)
    assert {"devices", "activities", "sync_runs", "settings"} <= tables(conn)
    models = {r["model"]: r["has_barometer"] for r in conn.execute("SELECT * FROM devices")}
    assert models == {"Forerunner 35": 0, "Forerunner 245": 0, "Forerunner 255": 1}


def test_failed_migration_is_rolled_back(conn, tmp_path):
    d = tmp_path / "migs"
    write(d, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    write(d, "0002_b.sql", "CREATE TABLE b (x INTEGER); INSERT INTO nope VALUES (1);")
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn, d)
    assert db.schema_version(conn) == 1
    assert "a" in tables(conn) and "b" not in tables(conn)
    # une fois corrigée, la migration passe
    write(d, "0002_b.sql", "CREATE TABLE b (x INTEGER);")
    assert db.migrate(conn, d) == ["0002_b.sql"]


def test_gap_in_numbering_is_rejected(tmp_path):
    d = tmp_path / "migs"
    write(d, "0001_a.sql", "SELECT 1;")
    write(d, "0003_c.sql", "SELECT 1;")
    with pytest.raises(RuntimeError, match="0003_c.sql"):
        db.load_migrations(d)


def test_database_newer_than_code_is_rejected(conn, tmp_path):
    d = tmp_path / "migs"
    write(d, "0001_a.sql", "SELECT 1;")
    conn.execute("PRAGMA user_version = 5")
    with pytest.raises(RuntimeError, match="plus récente"):
        db.migrate(conn, d)
