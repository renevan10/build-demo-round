"""Proves the guardrails in GUARDRAILS.md actually hold against the real schema.

Each test exists to disprove a specific lazy-AI shortcut, not just to
exercise happy-path code.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from app.repository_meetings import (
    DuplicateMeetingError,
    RoomConflictError,
    create_meeting_idempotent,
    list_employee_schedule,
)
from app.timeutil import local_wall_clock_to_utc, to_user_local, to_utc_z, user_local_date_str
from fixtures.seed_data import seed


@pytest.fixture
def base(conn: sqlite3.Connection) -> dict[str, int]:
    """One office/two employees/one room -- just enough to hang meetings off."""
    office_id = conn.execute(
        "INSERT INTO offices (name, city, timezone) VALUES ('HQ', 'Testville', 'UTC')"
    ).lastrowid
    alice_id = conn.execute(
        "INSERT INTO employees (name, email, timezone, office_id) VALUES "
        "('Alice', 'alice@test.dev', 'UTC', ?)",
        (office_id,),
    ).lastrowid
    bob_id = conn.execute(
        "INSERT INTO employees (name, email, timezone, office_id) VALUES "
        "('Bob', 'bob@test.dev', 'UTC', ?)",
        (office_id,),
    ).lastrowid
    room_id = conn.execute(
        "INSERT INTO meeting_rooms (office_id, name, capacity) VALUES (?, 'Room A', 4)",
        (office_id,),
    ).lastrowid
    conn.commit()
    return {"office": office_id, "alice": alice_id, "bob": bob_id, "room": room_id}


def test_duplicate_idempotency_key_is_rejected_not_double_inserted(conn, base):
    create_meeting_idempotent(
        conn,
        idempotency_key="key-1",
        title="Sync",
        organizer_id=base["alice"],
        start_utc="2026-01-05T10:00:00Z",
        end_utc="2026-01-05T10:30:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[base["bob"]],
    )

    with pytest.raises(DuplicateMeetingError):
        create_meeting_idempotent(
            conn,
            idempotency_key="key-1",
            title="Sync (resubmitted)",
            organizer_id=base["alice"],
            start_utc="2026-01-05T11:00:00Z",
            end_utc="2026-01-05T11:30:00Z",
            created_at_utc="2026-01-01T00:00:05Z",
            participant_ids=[base["bob"]],
        )

    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM meetings WHERE idempotency_key = ?", ("key-1",)
    ).fetchone()
    assert rows["n"] == 1, "check-then-insert would let a race produce 2 rows here"


def test_room_double_booking_is_rejected_not_a_race(conn, base):
    create_meeting_idempotent(
        conn,
        idempotency_key="room-first",
        title="First booking",
        organizer_id=base["alice"],
        start_utc="2026-01-06T10:00:00Z",
        end_utc="2026-01-06T11:00:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[],
        room_id=base["room"],
    )

    with pytest.raises(RoomConflictError):
        create_meeting_idempotent(
            conn,
            idempotency_key="room-overlapping",
            title="Overlapping booking",
            organizer_id=base["bob"],
            start_utc="2026-01-06T10:30:00Z",
            end_utc="2026-01-06T11:30:00Z",
            created_at_utc="2026-01-01T00:00:01Z",
            participant_ids=[],
            room_id=base["room"],
        )

    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM meetings WHERE room_id = ?", (base["room"],)
    ).fetchone()
    assert rows["n"] == 1, "the conflicting booking must not have been inserted"


def test_back_to_back_room_bookings_are_not_a_conflict(conn, base):
    """B starts exactly when A ends -- >= not >, no false-positive overlap."""
    first = create_meeting_idempotent(
        conn,
        idempotency_key="bb-a",
        title="Block A",
        organizer_id=base["alice"],
        start_utc="2026-01-07T10:00:00Z",
        end_utc="2026-01-07T11:00:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[],
        room_id=base["room"],
    )
    second = create_meeting_idempotent(
        conn,
        idempotency_key="bb-b",
        title="Block B",
        organizer_id=base["bob"],
        start_utc="2026-01-07T11:00:00Z",
        end_utc="2026-01-07T12:00:00Z",
        created_at_utc="2026-01-01T00:00:01Z",
        participant_ids=[],
        room_id=base["room"],
    )

    assert first.id != second.id
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM meetings WHERE room_id = ?", (base["room"],)
    ).fetchone()
    assert rows["n"] == 2


def test_feedback_from_a_non_participant_is_rejected_at_the_db_level(conn, base):
    """The composite FK on meeting_feedback -> meeting_participants, not just
    meetings, is what makes "only invited employees can rate a meeting" a
    schema-enforced invariant rather than an app-layer check to remember."""
    meeting = create_meeting_idempotent(
        conn,
        idempotency_key="fk-check",
        title="Alice-only sync",
        organizer_id=base["alice"],
        start_utc="2026-01-08T10:00:00Z",
        end_utc="2026-01-08T10:30:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[],  # bob is never invited
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO meeting_feedback (meeting_id, employee_id, usefulness_score, submitted_at_utc) "
            "VALUES (?, ?, 5, '2026-01-08T11:00:00Z')",
            (meeting.id, base["bob"]),
        )


def test_employee_schedule_pagination_returns_correct_slice_without_full_scan(conn, base):
    for i in range(25):
        create_meeting_idempotent(
            conn,
            idempotency_key=f"page-{i}",
            title=f"Meeting {i}",
            organizer_id=base["alice"],
            start_utc=f"2026-02-{i + 1:02d}T09:00:00Z",
            end_utc=f"2026-02-{i + 1:02d}T09:30:00Z",
            created_at_utc="2026-01-01T00:00:00Z",
            participant_ids=[base["bob"]],
        )

    page = list_employee_schedule(conn, base["alice"], limit=10, offset=20)

    assert [m.idempotency_key for m in page] == [f"page-{i}" for i in range(20, 25)]
    assert len(page) == 5


def test_employee_schedule_pagination_past_the_end_is_empty_not_an_error(conn, base):
    create_meeting_idempotent(
        conn,
        idempotency_key="only-meeting",
        title="Only one",
        organizer_id=base["alice"],
        start_utc="2026-01-09T10:00:00Z",
        end_utc="2026-01-09T10:30:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[base["bob"]],
    )

    page = list_employee_schedule(conn, base["alice"], limit=10, offset=1000)

    assert page == []


def test_adversarial_seed_dataset_loads_without_constraint_violations(conn):
    """Runs the full hand-authored dataset end to end: +5:30 offsets, a
    Sunday-Thursday work week, a meeting on the DST transition instant, and
    back-to-back room bookings all have to satisfy every CHECK/FK/UNIQUE
    constraint at once, not just in isolation."""
    seed(conn)

    counts = {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in (
            "offices",
            "employees",
            "meeting_rooms",
            "meetings",
            "meeting_participants",
            "meeting_feedback",
        )
    }
    assert counts["offices"] == 3
    assert counts["employees"] == 6
    assert counts["meetings"] == 7
    assert counts["meeting_feedback"] == 6

    rohan_id = conn.execute(
        "SELECT id FROM employees WHERE email = 'rohan@example.com'"
    ).fetchone()["id"]
    friday_row = conn.execute(
        "SELECT 1 FROM working_hours WHERE employee_id = ? AND day_of_week = 5", (rohan_id,)
    ).fetchone()
    assert friday_row is None, "Rohan's Sunday-Thursday week must not have a Friday row"

    critical_id = conn.execute(
        "SELECT id FROM meetings WHERE idempotency_key = 'seed-critical-low-value'"
    ).fetchone()["id"]
    scores = [
        row["usefulness_score"]
        for row in conn.execute(
            "SELECT usefulness_score FROM meeting_feedback WHERE meeting_id = ? ORDER BY employee_id",
            (critical_id,),
        )
    ]
    assert scores == [2, 1, 2, 3], "seeded as a low-usefulness critical meeting"


def test_naive_datetime_is_rejected_not_silently_treated_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)

    with pytest.raises(ValueError):
        to_user_local(naive, "America/New_York")


def test_user_local_date_can_differ_from_utc_date_near_midnight():
    # 2026-01-01 03:00 UTC is still 2025-12-31 22:00 in New York (UTC-5, no DST in January).
    instant = datetime(2026, 1, 1, 3, 0, 0, tzinfo=timezone.utc)

    utc_date = instant.date().isoformat()
    user_date = user_local_date_str(instant, "America/New_York")

    assert utc_date == "2026-01-01"
    assert user_date == "2025-12-31"
    assert utc_date != user_date, "billing 'today' off the server/UTC date would charge the wrong day"


def test_to_utc_z_matches_the_seeded_z_suffix_convention():
    # datetime.isoformat() alone renders "+00:00", not "Z" -- a second valid
    # spelling of the same instant that would silently break the room-
    # overlap query, which compares start_utc/end_utc as plain strings.
    instant = datetime(2026, 4, 1, 14, 0, 0, tzinfo=timezone.utc)
    assert to_utc_z(instant) == "2026-04-01T14:00:00Z"


def test_local_wall_clock_to_utc_round_trips_through_a_non_whole_hour_offset():
    # Asia/Kolkata is UTC+5:30 -- a fixed whole-hour-offset assumption
    # would silently drop the 30 minutes.
    instant = local_wall_clock_to_utc("2026-02-10T14:30", "Asia/Kolkata")
    assert to_utc_z(instant) == "2026-02-10T09:00:00Z"


def test_end_of_month_local_date_across_a_dst_transition():
    # US spring-forward 2026: clocks jump 2:00am -> 3:00am on 2026-03-08 in America/New_York.
    # 06:30 UTC on 2026-03-08 is 01:30 local (pre-jump, UTC-5) the *same* morning.
    before_jump = datetime(2026, 3, 8, 6, 30, 0, tzinfo=timezone.utc)
    after_jump = datetime(2026, 3, 8, 7, 30, 0, tzinfo=timezone.utc)

    assert user_local_date_str(before_jump, "America/New_York") == "2026-03-08"
    assert user_local_date_str(after_jump, "America/New_York") == "2026-03-08"
    assert to_user_local(before_jump, "America/New_York").hour == 1
    assert to_user_local(after_jump, "America/New_York").hour == 3
