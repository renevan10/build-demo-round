"""SQLite connection + a hand-rolled migration runner.

Swap-out point for production: replace `connect()`'s sqlite3 connection with a
pooled Postgres connection, keep every function below returning/consuming the
same DB-API-shaped connection so repository code doesn't change.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(db_path: str) -> sqlite3.Connection:
    # isolation_level=None puts the connection in autocommit mode, so the
    # sqlite3 module never opens an implicit transaction ahead of a DML
    # statement. Without this, an explicit `BEGIN IMMEDIATE` (see
    # app/repository_meetings.py) fails with "cannot start a transaction
    # within a transaction" the moment an earlier, uncommitted INSERT has
    # already opened one -- every transaction boundary here is explicit.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every *.sql file in migrations_dir, in filename order, exactly once.

    Returns the filenames applied this call (empty if already up to date).
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    applied_rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    already_applied = {row["filename"] for row in applied_rows}

    newly_applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in already_applied:
            continue
        script = path.read_text(encoding="utf-8")
        conn.executescript(script)
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,)
        )
        newly_applied.append(path.name)

    conn.commit()
    return newly_applied
