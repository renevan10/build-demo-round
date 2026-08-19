"""Meeting creation and lookup.

Two guardrail patterns carried over from the scaffold's demo repository, now
against the real schema: DB-enforced uniqueness instead of check-then-insert,
and SQL-side filtering/pagination instead of loading every row into Python.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


class DuplicateMeetingError(Exception):
    def __init__(self, idempotency_key: str):
        super().__init__(f"meeting already exists for key {idempotency_key!r}")
        self.idempotency_key = idempotency_key


class RoomConflictError(Exception):
    def __init__(self, room_id: int, start_utc: str, end_utc: str):
        super().__init__(
            f"room {room_id} is already booked during [{start_utc}, {end_utc})"
        )
        self.room_id = room_id


@dataclass(frozen=True)
class Meeting:
    id: int
    title: str
    organizer_id: int
    start_utc: str
    end_utc: str
    room_id: int | None
    priority: str
    status: str
    idempotency_key: str
    created_at_utc: str


def create_meeting_idempotent(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    title: str,
    organizer_id: int,
    start_utc: str,
    end_utc: str,
    created_at_utc: str,
    participant_ids: list[int],
    room_id: int | None = None,
    priority: str = "medium",
) -> Meeting:
    """Insert a meeting plus its participants, race-safe on both axes.

    Isolation strategy: `BEGIN IMMEDIATE` acquires SQLite's single write lock
    *before* the room-overlap check runs, so a second concurrent request for
    the same room+time blocks until the first transaction commits or rolls
    back -- there's no gap between "checked, looked free" and "inserted" for
    another writer to land in. That's what makes the overlap SELECT below
    safe as a check-then-insert, unlike the naive version of that pattern.

    The idempotency-key axis doesn't even need the overlap check: the
    UNIQUE constraint on meetings.idempotency_key is the serialization point,
    the same pattern as the scaffold's create_idempotent.

    Overlap test is a standard interval-intersection, half-open on `end`:
    existing.start_utc < new.end_utc AND existing.end_utc > new.start_utc.
    A meeting ending exactly when another starts does NOT conflict.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        if room_id is not None:
            conflict = conn.execute(
                "SELECT 1 FROM meetings "
                "WHERE room_id = ? AND status != 'cancelled' "
                "AND start_utc < ? AND end_utc > ? LIMIT 1",
                (room_id, end_utc, start_utc),
            ).fetchone()
            if conflict is not None:
                conn.rollback()
                raise RoomConflictError(room_id, start_utc, end_utc)

        cursor = conn.execute(
            "INSERT INTO meetings "
            "(title, organizer_id, start_utc, end_utc, room_id, priority, "
            " idempotency_key, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                organizer_id,
                start_utc,
                end_utc,
                room_id,
                priority,
                idempotency_key,
                created_at_utc,
            ),
        )
        meeting_id = cursor.lastrowid

        attendees = set(participant_ids) | {organizer_id}
        conn.executemany(
            "INSERT INTO meeting_participants (meeting_id, employee_id, attendance_role) "
            "VALUES (?, ?, 'required')",
            [(meeting_id, employee_id) for employee_id in attendees],
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise DuplicateMeetingError(idempotency_key) from exc

    return Meeting(
        meeting_id,
        title,
        organizer_id,
        start_utc,
        end_utc,
        room_id,
        priority,
        "scheduled",
        idempotency_key,
        created_at_utc,
    )


def list_employee_schedule(
    conn: sqlite3.Connection, employee_id: int, limit: int, offset: int = 0
) -> list[Meeting]:
    """Page through one employee's meetings, ordered soonest-first.

    Joins through meeting_participants and filters/sorts/limits in SQL, not
    by pulling every meeting into Python and slicing.
    """
    rows = conn.execute(
        "SELECT m.id, m.title, m.organizer_id, m.start_utc, m.end_utc, m.room_id, "
        "       m.priority, m.status, m.idempotency_key, m.created_at_utc "
        "FROM meetings m "
        "JOIN meeting_participants mp ON mp.meeting_id = m.id "
        "WHERE mp.employee_id = ? "
        "ORDER BY m.start_utc LIMIT ? OFFSET ?",
        (employee_id, limit, offset),
    ).fetchall()
    return [Meeting(**dict(row)) for row in rows]
