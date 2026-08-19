"""Hand-authored adversarial dataset for the meeting scheduler.

Not happy-path rows: every entity here is chosen to break a specific default
assumption (whole-hour UTC offsets, Mon-Fri work weeks, DST transitions,
back-to-back room bookings, timezone-vs-office mismatches). See
DESIGN-timezone-scheduler.md and GUARDRAILS.md for the categories this is
drawn from.

Run directly to seed app.db:
    python -m fixtures.seed_data
"""

from __future__ import annotations

import os
import sqlite3

from app.db import connect, run_migrations
from app.repository_meetings import create_meeting_idempotent


def seed(conn: sqlite3.Connection) -> None:
    office_ids = _seed_offices(conn)
    employee_ids = _seed_employees(conn, office_ids)
    room_ids = _seed_rooms(conn, office_ids)
    _seed_working_hours(conn, employee_ids)
    _seed_blackouts(conn, employee_ids)
    _seed_meetings(conn, employee_ids, room_ids)
    conn.commit()


def _seed_offices(conn: sqlite3.Connection) -> dict[str, int]:
    rows = [
        ("nyc", "NYC HQ", "New York", "America/New_York"),
        ("london", "London", "London", "Europe/London"),
        ("blr", "Bangalore", "Bangalore", "Asia/Kolkata"),
    ]
    ids = {}
    for key, name, city, tz in rows:
        cur = conn.execute(
            "INSERT INTO offices (name, city, timezone) VALUES (?, ?, ?)",
            (name, city, tz),
        )
        ids[key] = cur.lastrowid
    return ids


def _seed_employees(conn: sqlite3.Connection, office_ids: dict[str, int]) -> dict[str, int]:
    rows = [
        # key, name, email, timezone, office_key
        ("alice", "Alice Chen", "alice@example.com", "America/New_York", "nyc"),
        ("bob", "Bob Okafor", "bob@example.com", "America/New_York", "nyc"),
        # +5:30 offset -- breaks any code that assumes whole-hour offsets
        ("priya", "Priya Nair", "priya@example.com", "Asia/Kolkata", "blr"),
        # Sunday-Thursday work week (seeded in _seed_working_hours)
        ("rohan", "Rohan Mehta", "rohan@example.com", "Asia/Kolkata", "blr"),
        ("emma", "Emma Clarke", "emma@example.com", "Europe/London", "london"),
        # Nominally NYC office, but actually working from Seoul --
        # employee.timezone != their office's timezone
        ("david", "David Kim", "david@example.com", "Asia/Seoul", "nyc"),
    ]
    ids = {}
    for key, name, email, tz, office_key in rows:
        cur = conn.execute(
            "INSERT INTO employees (name, email, timezone, office_id) VALUES (?, ?, ?, ?)",
            (name, email, tz, office_ids[office_key]),
        )
        ids[key] = cur.lastrowid
    return ids


def _seed_rooms(conn: sqlite3.Connection, office_ids: dict[str, int]) -> dict[str, int]:
    rows = [
        ("hudson", "Hudson", "nyc", 8),
        ("liberty", "Liberty", "nyc", 4),
        ("thames", "Thames", "london", 6),
        ("indiranagar", "Indiranagar", "blr", 10),
    ]
    ids = {}
    for key, name, office_key, capacity in rows:
        cur = conn.execute(
            "INSERT INTO meeting_rooms (office_id, name, capacity) VALUES (?, ?, ?)",
            (office_ids[office_key], name, capacity),
        )
        ids[key] = cur.lastrowid
    return ids


def _seed_working_hours(conn: sqlite3.Connection, employee_ids: dict[str, int]) -> None:
    mon_fri_9_5 = [(d, "09:00", "17:00") for d in range(1, 6)]  # ISO Mon=1 .. Fri=5
    sun_thu_9_6 = [(d, "09:00", "18:00") for d in (7, 1, 2, 3, 4)]  # Sun=7, Mon..Thu

    for key in ("alice", "bob", "priya", "emma", "david"):
        for day, start, end in mon_fri_9_5:
            conn.execute(
                "INSERT INTO working_hours (employee_id, day_of_week, start_local, end_local) "
                "VALUES (?, ?, ?, ?)",
                (employee_ids[key], day, start, end),
            )

    # Rohan: Sunday-Thursday work week -- no Friday/Saturday rows at all,
    # the case a Mon-Fri-only assumption would silently get wrong.
    for day, start, end in sun_thu_9_6:
        conn.execute(
            "INSERT INTO working_hours (employee_id, day_of_week, start_local, end_local) "
            "VALUES (?, ?, ?, ?)",
            (employee_ids["rohan"], day, start, end),
        )


def _seed_blackouts(conn: sqlite3.Connection, employee_ids: dict[str, int]) -> None:
    # Local calendar date in the employee's own timezone -- would land on the
    # wrong UTC day if converted naively instead of via her own tz.
    conn.execute(
        "INSERT INTO blackouts (employee_id, local_date, reason) VALUES (?, ?, ?)",
        (employee_ids["priya"], "2026-03-10", "festival holiday"),
    )


def _seed_meetings(
    conn: sqlite3.Connection, employee_ids: dict[str, int], room_ids: dict[str, int]
) -> None:
    e, r = employee_ids, room_ids

    # Three participants, three non-whole-hour-offset zones at once
    # (Kolkata +5:30, Seoul +9:00, London +0) -- virtual, no room.
    create_meeting_idempotent(
        conn,
        idempotency_key="seed-cross-tz-standup",
        title="Cross-Timezone Standup",
        organizer_id=e["emma"],
        start_utc="2026-02-10T09:00:00Z",
        end_utc="2026-02-10T09:30:00Z",
        created_at_utc="2026-02-01T00:00:00Z",
        participant_ids=[e["priya"], e["david"], e["emma"]],
        room_id=None,
        priority="medium",
    )

    # Sits exactly on the US spring-forward instant (clocks jump
    # 2:00am -> 3:00am America/New_York on 2026-03-08). A fixed-offset
    # conversion instead of real zoneinfo would place this an hour off.
    create_meeting_idempotent(
        conn,
        idempotency_key="seed-dst-transition-sync",
        title="DST Transition Sync",
        organizer_id=e["alice"],
        start_utc="2026-03-08T07:00:00Z",
        end_utc="2026-03-08T07:30:00Z",
        created_at_utc="2026-02-01T00:00:00Z",
        participant_ids=[e["alice"], e["bob"], e["emma"]],
        room_id=r["hudson"],
        priority="high",
    )

    # Back-to-back in the same room: B starts exactly when A ends. Proves
    # the overlap check is half-open and doesn't false-positive on a shared
    # boundary instant.
    create_meeting_idempotent(
        conn,
        idempotency_key="seed-boundary-a",
        title="Boundary Block A",
        organizer_id=e["bob"],
        start_utc="2026-02-11T15:00:00Z",
        end_utc="2026-02-11T16:00:00Z",
        created_at_utc="2026-02-01T00:00:00Z",
        participant_ids=[e["bob"]],
        room_id=r["liberty"],
        priority="low",
    )
    create_meeting_idempotent(
        conn,
        idempotency_key="seed-boundary-b",
        title="Boundary Block B",
        organizer_id=e["bob"],
        start_utc="2026-02-11T16:00:00Z",
        end_utc="2026-02-11T17:00:00Z",
        created_at_utc="2026-02-01T00:00:00Z",
        participant_ids=[e["bob"]],
        room_id=r["liberty"],
        priority="low",
    )

    # 2026-02-08 is a Sunday: a normal working day for Rohan, a weekend for
    # everyone else in this dataset.
    create_meeting_idempotent(
        conn,
        idempotency_key="seed-sunday-sync",
        title="Sunday Vendor Sync",
        organizer_id=e["rohan"],
        start_utc="2026-02-08T05:00:00Z",
        end_utc="2026-02-08T06:00:00Z",
        created_at_utc="2026-02-01T00:00:00Z",
        participant_ids=[e["rohan"], e["priya"]],
        room_id=r["indiranagar"],
        priority="medium",
    )

    # Completed, critical-priority, rated low by everyone who attended --
    # the "expensive but not useful" case the feedback loop exists to catch.
    critical = create_meeting_idempotent(
        conn,
        idempotency_key="seed-critical-low-value",
        title="All-Hands Status Review",
        organizer_id=e["alice"],
        start_utc="2026-01-15T14:00:00Z",
        end_utc="2026-01-15T15:30:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[e["alice"], e["bob"], e["emma"], e["david"]],
        room_id=r["hudson"],
        priority="critical",
    )
    conn.execute("UPDATE meetings SET status = 'completed' WHERE id = ?", (critical.id,))
    conn.executemany(
        "INSERT INTO meeting_feedback (meeting_id, employee_id, usefulness_score, submitted_at_utc) "
        "VALUES (?, ?, ?, '2026-01-15T16:00:00Z')",
        [
            (critical.id, e["alice"], 2),
            (critical.id, e["bob"], 1),
            (critical.id, e["emma"], 2),
            (critical.id, e["david"], 3),
        ],
    )

    # Mirror case: low priority, rated high by everyone -- so the dashboard
    # isn't just "critical = bad, low = good" by construction.
    valuable = create_meeting_idempotent(
        conn,
        idempotency_key="seed-low-priority-high-value",
        title="1:1 Mentoring Session",
        organizer_id=e["priya"],
        start_utc="2026-01-20T05:30:00Z",
        end_utc="2026-01-20T06:00:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[e["priya"], e["rohan"]],
        room_id=None,
        priority="low",
    )
    conn.execute("UPDATE meetings SET status = 'completed' WHERE id = ?", (valuable.id,))
    conn.executemany(
        "INSERT INTO meeting_feedback (meeting_id, employee_id, usefulness_score, submitted_at_utc) "
        "VALUES (?, ?, ?, '2026-01-20T06:30:00Z')",
        [(valuable.id, e["priya"], 5), (valuable.id, e["rohan"], 5)],
    )


if __name__ == "__main__":
    db_path = os.environ.get("APP_DB_PATH", "app.db")
    connection = connect(db_path)
    run_migrations(connection)
    seed(connection)
    connection.close()
    print(f"Seeded adversarial dataset into {db_path}")
