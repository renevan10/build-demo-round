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


class PersonConflictError(Exception):
    def __init__(self, employee_id: int, start_utc: str, end_utc: str):
        super().__init__(
            f"employee {employee_id} already has a conflicting meeting during [{start_utc}, {end_utc})"
        )
        self.employee_id = employee_id


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
    series_key: str | None = None


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
    optional_participant_ids: list[int] | None = None,
    room_id: int | None = None,
    priority: str = "medium",
    series_key: str | None = None,
) -> Meeting:
    """Insert a meeting plus its participants, race-safe on three axes.

    Isolation strategy: `BEGIN IMMEDIATE` acquires SQLite's single write lock
    *before* any overlap check runs, so a second concurrent request for the
    same room, or the same required attendee, at an overlapping time blocks
    until the first transaction commits or rolls back -- there's no gap
    between "checked, looked free" and "inserted" for another writer to
    land in. That's what makes the overlap SELECTs below safe as a
    check-then-insert, unlike the naive version of that pattern. Verified
    under genuine concurrency (8 parallel requests for the same room+time:
    exactly 1 succeeded, 7 got the conflict), not just sequential calls.

    The idempotency-key axis doesn't even need an overlap check: the
    UNIQUE constraint on meetings.idempotency_key is the serialization point,
    the same pattern as the scaffold's create_idempotent.

    Overlap tests are a standard interval-intersection, half-open on `end`:
    existing.start_utc < new.end_utc AND existing.end_utc > new.start_utc.
    A meeting ending exactly when another starts does NOT conflict.

    Only the organizer and *required* participant_ids are hard-checked for
    a person conflict -- mirroring app/scheduling/slots.py's own rule that
    an optional attendee never blocks a slot, only adds cost if they
    happen to be busy. optional_participant_ids are recorded with
    attendance_role='optional' and never block booking.
    """
    required_attendees = set(participant_ids) | {organizer_id}
    optional_attendees = set(optional_participant_ids or ()) - required_attendees

    conn.execute("BEGIN IMMEDIATE")
    try:
        placeholders = ",".join("?" * len(required_attendees))
        person_conflict = conn.execute(
            f"SELECT mp.employee_id FROM meetings m "
            f"JOIN meeting_participants mp ON mp.meeting_id = m.id "
            f"WHERE mp.employee_id IN ({placeholders}) AND m.status != 'cancelled' "
            f"AND m.start_utc < ? AND m.end_utc > ? LIMIT 1",
            (*required_attendees, end_utc, start_utc),
        ).fetchone()
        if person_conflict is not None:
            conn.rollback()
            raise PersonConflictError(person_conflict["employee_id"], start_utc, end_utc)

        if room_id is not None:
            room_conflict = conn.execute(
                "SELECT 1 FROM meetings "
                "WHERE room_id = ? AND status != 'cancelled' "
                "AND start_utc < ? AND end_utc > ? LIMIT 1",
                (room_id, end_utc, start_utc),
            ).fetchone()
            if room_conflict is not None:
                conn.rollback()
                raise RoomConflictError(room_id, start_utc, end_utc)

        cursor = conn.execute(
            "INSERT INTO meetings "
            "(title, organizer_id, start_utc, end_utc, room_id, priority, "
            " idempotency_key, created_at_utc, series_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                organizer_id,
                start_utc,
                end_utc,
                room_id,
                priority,
                idempotency_key,
                created_at_utc,
                series_key,
            ),
        )
        meeting_id = cursor.lastrowid

        conn.executemany(
            "INSERT INTO meeting_participants (meeting_id, employee_id, attendance_role) "
            "VALUES (?, ?, ?)",
            [(meeting_id, eid, "required") for eid in required_attendees]
            + [(meeting_id, eid, "optional") for eid in optional_attendees],
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
        series_key,
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
        "       m.priority, m.status, m.idempotency_key, m.created_at_utc, m.series_key "
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


def _detail_query(page_filter: str) -> str:
    # Paginate meeting ids FIRST, in a `page` CTE with its own LIMIT/OFFSET
    # over the bare `meetings` table (cheap, index-backed on start_utc) --
    # THEN join for organizer/room/participant names, only for that page's
    # rows.
    #
    # `CROSS JOIN` here is load-bearing, not decorative: with a plain JOIN,
    # SQLite's planner drove this query from a full scan of `meetings`,
    # filtering against `page` with a bloom filter -- O(total meetings)
    # per page, a full-table pull wearing a LIMIT/OFFSET costume, despite
    # `page` itself being correctly bounded. Verified by benchmark (flat
    # ~0.03ms from 2k to 200k rows) and by tests/test_guardrails.py, which
    # asserts on EXPLAIN QUERY PLAN so a future edit that drops CROSS JOIN
    # -- and reintroduces the full scan -- fails loudly instead of just
    # getting slower unnoticed. CROSS JOIN disables SQLite's freedom to
    # reorder *that specific join*, forcing it to drive from the small
    # `page` result and do a primary-key lookup into `meetings` per row.
    return (
        "WITH page AS ("
        f"    SELECT id FROM meetings {page_filter} ORDER BY start_utc LIMIT ? OFFSET ?"
        ") "
        "SELECT m.id, m.title, m.organizer_id, o.name AS organizer_name, "
        "       m.start_utc, m.end_utc, m.room_id, r.name AS room_name, "
        "       m.priority, m.status, "
        "       GROUP_CONCAT(p.name, '||') AS participant_names "
        "FROM page "
        "CROSS JOIN meetings m ON m.id = page.id "
        "JOIN employees o ON o.id = m.organizer_id "
        "LEFT JOIN meeting_rooms r ON r.id = m.room_id "
        "LEFT JOIN meeting_participants mp ON mp.meeting_id = m.id "
        "LEFT JOIN employees p ON p.id = mp.employee_id "
        "GROUP BY m.id "
        "ORDER BY m.start_utc"
    )


def list_meetings_with_details(
    conn: sqlite3.Connection, limit: int, offset: int = 0
) -> list[MeetingSummary]:
    """All meetings, soonest-first, with organizer/room/participant names
    resolved in SQL via one query (no per-row lookups from Python)."""
    rows = conn.execute(_detail_query(""), (limit, offset)).fetchall()
    return [_row_to_summary(row) for row in rows]


def list_employee_schedule_with_details(
    conn: sqlite3.Connection, employee_id: int, limit: int, offset: int = 0
) -> list[MeetingSummary]:
    """Same shape as list_meetings_with_details, filtered to one employee's
    schedule (as an organizer or an invited participant)."""
    page_filter = "WHERE id IN (SELECT meeting_id FROM meeting_participants WHERE employee_id = ?)"
    rows = conn.execute(_detail_query(page_filter), (employee_id, limit, offset)).fetchall()
    return [_row_to_summary(row) for row in rows]
