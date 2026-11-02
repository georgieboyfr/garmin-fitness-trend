"""
Base SQLite et migrations.

Les migrations sont des fichiers SQL numérotés (app/migrations/0001_xxx.sql), appliqués
dans l'ordre au démarrage. La version courante est stockée dans PRAGMA user_version ;
chaque migration est appliquée dans sa propre transaction, avec la mise à jour de la
version : une migration qui échoue ne laisse rien à moitié fait.
"""
import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger("db")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def load_migrations(directory=MIGRATIONS_DIR):
    """Liste triée de (version, nom, sql). Vérifie que la numérotation se suit sans trou."""
    found = []
    for p in Path(directory).iterdir():
        m = _MIGRATION_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p.name, p.read_text(encoding="utf-8")))
    found.sort()
    for expected, (version, name, _) in enumerate(found, 1):
        if version != expected:
            raise RuntimeError(f"Migration manquante ou en double avant {name} (attendu {expected:04d})")
    return found


def schema_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn, directory=MIGRATIONS_DIR):
    """Applique les migrations manquantes. Retourne la liste des noms appliqués."""
    migrations = load_migrations(directory)
    current = schema_version(conn)
    if current > len(migrations):
        raise RuntimeError(
            f"La base est en version {current}, plus récente que le code ({len(migrations)}) : "
            "utilise une image plus récente ou restaure une sauvegarde."
        )
    applied = []
    for version, name, sql in migrations[current:]:
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            log.exception("Migration %s échouée", name)
            raise
        log.info("Migration appliquée : %s", name)
        applied.append(name)
    return applied
