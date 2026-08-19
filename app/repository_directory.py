"""Read-only lookups for offices, employees, and meeting rooms.

Small, mostly-static tables in this dataset, but still filtered/sorted in
SQL and paginated rather than loaded whole into Python -- same discipline
as the meeting queries, so it doesn't stop being true if the company grows.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Office:
    id: int
    name: str
    city: str
    timezone: str


@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    email: str
    timezone: str
    office_id: int


@dataclass(frozen=True)
class MeetingRoom:
    id: int
    office_id: int
    name: str
    capacity: int


def list_offices(conn: sqlite3.Connection, limit: int = 200, offset: int = 0) -> list[Office]:
    rows = conn.execute(
        "SELECT id, name, city, timezone FROM offices ORDER BY name LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [Office(**dict(row)) for row in rows]


def list_employees(conn: sqlite3.Connection, limit: int = 200, offset: int = 0) -> list[Employee]:
    rows = conn.execute(
        "SELECT id, name, email, timezone, office_id FROM employees "
        "ORDER BY name LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [Employee(**dict(row)) for row in rows]


def list_meeting_rooms(
    conn: sqlite3.Connection, office_id: int | None = None, limit: int = 200, offset: int = 0
) -> list[MeetingRoom]:
    if office_id is None:
        rows = conn.execute(
            "SELECT id, office_id, name, capacity FROM meeting_rooms "
            "ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, office_id, name, capacity FROM meeting_rooms "
            "WHERE office_id = ? ORDER BY name LIMIT ? OFFSET ?",
            (office_id, limit, offset),
        ).fetchall()
    return [MeetingRoom(**dict(row)) for row in rows]
