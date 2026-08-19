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
        # Only a collision on the idempotency key means "duplicate
        # submission" -- a CHECK (e.g. end_utc <= start_utc, bad priority)
        # or FOREIGN KEY (unknown organizer/participant/room) violation is a
        # different failure and must not be mislabeled as one.
        if "idempotency_key" in str(exc):
            raise DuplicateMeetingError(idempotency_key) from exc
        raise

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


@dataclass(frozen=True)
class MeetingSummary:
    """A meeting joined with the display names the frontend needs, instead
    of making it stitch together id -> name lookups itself."""

    id: int
    title: str
    organizer_id: int
    organizer_name: str
    start_utc: str
    end_utc: str
    room_id: int | None
    room_name: str | None
    priority: str
    status: str
    participant_names: list[str]


def _row_to_summary(row: sqlite3.Row) -> MeetingSummary:
    raw_names = row["participant_names"]
    return MeetingSummary(
        id=row["id"],
        title=row["title"],
        organizer_id=row["organizer_id"],
        organizer_name=row["organizer_name"],
        start_utc=row["start_utc"],
        end_utc=row["end_utc"],
        room_id=row["room_id"],
        room_name=row["room_name"],
        priority=row["priority"],
        status=row["status"],
        participant_names=raw_names.split("||") if raw_names else [],
    )


_DETAIL_QUERY = (
    "SELECT m.id, m.title, m.organizer_id, o.name AS organizer_name, "
    "       m.start_utc, m.end_utc, m.room_id, r.name AS room_name, "
    "       m.priority, m.status, "
    "       GROUP_CONCAT(p.name, '||') AS participant_names "
    "FROM meetings m "
    "JOIN employees o ON o.id = m.organizer_id "
    "LEFT JOIN meeting_rooms r ON r.id = m.room_id "
    "LEFT JOIN meeting_participants mp ON mp.meeting_id = m.id "
    "LEFT JOIN employees p ON p.id = mp.employee_id "
)


def list_meetings_with_details(
    conn: sqlite3.Connection, limit: int, offset: int = 0
) -> list[MeetingSummary]:
    """All meetings, soonest-first, with organizer/room/participant names
    resolved in SQL via one query (no per-row lookups from Python)."""
    rows = conn.execute(
        _DETAIL_QUERY + "GROUP BY m.id ORDER BY m.start_utc LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [_row_to_summary(row) for row in rows]


def list_employee_schedule_with_details(
    conn: sqlite3.Connection, employee_id: int, limit: int, offset: int = 0
) -> list[MeetingSummary]:
    """Same shape as list_meetings_with_details, filtered to one employee's
    schedule (as an organizer or an invited participant)."""
    rows = conn.execute(
        _DETAIL_QUERY
        + "WHERE m.id IN (SELECT meeting_id FROM meeting_participants WHERE employee_id = ?) "
        + "GROUP BY m.id ORDER BY m.start_utc LIMIT ? OFFSET ?",
        (employee_id, limit, offset),
    ).fetchall()
    return [_row_to_summary(row) for row in rows]
