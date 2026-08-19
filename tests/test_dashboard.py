"""Proves the meeting-time dashboard attributes hours to each employee's
own local calendar day, not a shared UTC day -- the same guardrail this
project has cared about everywhere else timezone math happens, now
applied to reporting instead of scheduling.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.dashboard import MeetingAttendance, summarize_meeting_time
from app.repository_dashboard import get_attendances_in_utc_window


def test_total_hours_and_meeting_count_for_a_single_attendance():
    attendances = [MeetingAttendance(1, "2026-01-05T10:00:00Z", "2026-01-05T11:30:00Z")]

    results = summarize_meeting_time(
        attendances,
        employee_timezones={1: "UTC"},
        employee_names={1: "Alice"},
        range_start_date=date(2026, 1, 1),
        range_end_date=date(2026, 1, 31),
    )

    assert len(results) == 1
    assert results[0].total_hours == 1.5
    assert results[0].meeting_count == 1


def test_employee_with_zero_meetings_still_appears_with_zero_hours():
    results = summarize_meeting_time(
        [],
        employee_timezones={1: "UTC", 2: "UTC"},
        employee_names={1: "Alice", 2: "Bob"},
        range_start_date=date(2026, 1, 1),
        range_end_date=date(2026, 1, 31),
    )

    assert {r.employee_id for r in results} == {1, 2}
    assert all(r.total_hours == 0.0 and r.meeting_count == 0 for r in results)


def test_a_meeting_is_attributed_to_the_employees_own_local_date_not_utc():
    """2026-01-04T19:00:00Z is still 2026-01-04 in UTC, but it's already
    2026-01-05T00:30 in Asia/Kolkata (+5:30). A range of exactly Jan 5 must
    include this meeting for a Kolkata employee -- excluding it because
    its UTC date is Jan 4 would be the naive-UTC-date bug this project's
    guardrails exist to catch, just in a reporting query instead of a
    scheduling one."""
    attendances = [MeetingAttendance(1, "2026-01-04T19:00:00Z", "2026-01-04T19:30:00Z")]

    results = summarize_meeting_time(
        attendances,
        employee_timezones={1: "Asia/Kolkata"},
        employee_names={1: "Priya"},
        range_start_date=date(2026, 1, 5),
        range_end_date=date(2026, 1, 5),
    )

    assert results[0].meeting_count == 1, "the meeting's Kolkata-local date (Jan 5) must count, not its UTC date (Jan 4)"
    assert results[0].total_hours == 0.5


def test_a_meeting_outside_the_range_is_excluded():
    attendances = [MeetingAttendance(1, "2026-02-01T10:00:00Z", "2026-02-01T11:00:00Z")]

    results = summarize_meeting_time(
        attendances,
        employee_timezones={1: "UTC"},
        employee_names={1: "Alice"},
        range_start_date=date(2026, 1, 1),
        range_end_date=date(2026, 1, 31),
    )

    assert results[0].meeting_count == 0
    assert results[0].total_hours == 0.0


def test_avg_hours_per_week_matches_total_for_an_exact_seven_day_range():
    attendances = [MeetingAttendance(1, "2026-01-05T10:00:00Z", "2026-01-05T17:00:00Z")]  # 7 hours

    results = summarize_meeting_time(
        attendances,
        employee_timezones={1: "UTC"},
        employee_names={1: "Alice"},
        range_start_date=date(2026, 1, 1),
        range_end_date=date(2026, 1, 7),  # exactly 7 days
    )

    assert results[0].total_hours == 7.0
    assert results[0].avg_hours_per_week == 7.0
    assert results[0].avg_hours_per_day == 1.0


def test_range_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        summarize_meeting_time(
            [],
            employee_timezones={1: "UTC"},
            employee_names={1: "Alice"},
            range_start_date=date(2026, 1, 10),
            range_end_date=date(2026, 1, 1),
        )


def test_cancelled_meetings_are_excluded_from_the_utc_window_fetch(conn):
    from app.repository_meetings import create_meeting_idempotent

    office_id = conn.execute(
        "INSERT INTO offices (name, city, timezone) VALUES ('HQ', 'Testville', 'UTC')"
    ).lastrowid
    alice_id = conn.execute(
        "INSERT INTO employees (name, email, timezone, office_id) VALUES ('Alice', 'a@t.dev', 'UTC', ?)",
        (office_id,),
    ).lastrowid
    conn.commit()

    meeting = create_meeting_idempotent(
        conn,
        idempotency_key="dashboard-cancel-check",
        title="Will be cancelled",
        organizer_id=alice_id,
        start_utc="2026-01-05T10:00:00Z",
        end_utc="2026-01-05T11:00:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[],
    )
    conn.execute("UPDATE meetings SET status = 'cancelled' WHERE id = ?", (meeting.id,))
    conn.commit()

    attendances = get_attendances_in_utc_window(conn, "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")

    assert attendances == [], "a cancelled meeting must not count toward anyone's meeting time"
