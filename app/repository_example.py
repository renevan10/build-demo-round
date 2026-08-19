"""Two reference patterns for `demo_events` — delete once you have a real schema.

Keep the *shape* of these two functions when you write your own repository
code: DB-enforced uniqueness instead of check-then-insert, and SQL-side
filtering/pagination instead of loading every row into Python.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


class DuplicateEventError(Exception):
    def __init__(self, idempotency_key: str):
        super().__init__(f"event already exists for key {idempotency_key!r}")
        self.idempotency_key = idempotency_key


@dataclass(frozen=True)
class DemoEvent:
    id: int
    idempotency_key: str
    payload: str
    created_at_utc: str


def create_idempotent(
    conn: sqlite3.Connection, idempotency_key: str, payload: str, created_at_utc: str
) -> DemoEvent:
    """Insert-or-reject on a duplicate key, race-safe.

    The lazy version is `SELECT ... WHERE key = ?` then `INSERT` if nothing
    came back — that has a gap between the check and the insert where two
    concurrent requests both see "not found" and both insert, producing two
    rows for one idempotency key. Here the UNIQUE constraint on
    `idempotency_key` (see migrations/0001_init.sql) makes SQLite itself the
    serialization point: the second writer gets IntegrityError, not a race.
    """
    try:
        cursor = conn.execute(
            "INSERT INTO demo_events (idempotency_key, payload, created_at_utc) "
            "VALUES (?, ?, ?)",
            (idempotency_key, payload, created_at_utc),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise DuplicateEventError(idempotency_key) from exc

    return DemoEvent(cursor.lastrowid, idempotency_key, payload, created_at_utc)


def list_paginated(
    conn: sqlite3.Connection, limit: int, offset: int = 0
) -> list[DemoEvent]:
    """Page through events without ever pulling the full table into memory.

    The lazy version is `SELECT * FROM demo_events` followed by Python-side
    slicing — that's an O(n) memory and I/O cost per request no matter how
    small the page is, and it gets worse every day the table grows. LIMIT/
    OFFSET (or, for a real production table, a keyset/cursor on an indexed
    column) keeps the cost proportional to the page size.
    """
    rows = conn.execute(
        "SELECT id, idempotency_key, payload, created_at_utc "
        "FROM demo_events ORDER BY id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [DemoEvent(**dict(row)) for row in rows]
