"""Proves the meeting-time dashboard attributes hours to each employee's
own local calendar day, not a shared UTC day -- the same guardrail this
project has cared about everywhere else timezone math happens, now
applied to reporting instead of scheduling.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.dashboard import (
    MeetingAttendance,
    MeetingUsefulnessRecord,
    summarize_meeting_time,
    summarize_usefulness,
)
from app.repository_dashboard import get_attendances_in_utc_window, get_meeting_usefulness_in_utc_window


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


NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)  # after everything below has already happened


def _record(
    meeting_id, priority, organizer_id=1, organizer_name="Alice", feedback_count=0, feedback_sum=0
) -> MeetingUsefulnessRecord:
    return MeetingUsefulnessRecord(
        meeting_id=meeting_id,
        title=f"Meeting {meeting_id}",
        priority=priority,
        organizer_id=organizer_id,
        organizer_name=organizer_name,
        start_utc="2026-01-05T10:00:00Z",
        end_utc="2026-01-05T10:30:00Z",
        feedback_count=feedback_count,
        feedback_sum=feedback_sum,
    )


def test_by_priority_average_is_weighted_by_rating_count_not_averaged_per_meeting():
    """Meeting A: one rating of 5. Meeting B: three ratings summing to 3
    (avg 1 each). Naive average-of-per-meeting-averages gives (5+1)/2=3.0;
    the correct rating-weighted average is (5+1+1+1)/4=2.0. This is
    exactly why the repository query returns (count, sum) per meeting
    instead of a pre-averaged score."""
    records = [
        _record(1, "high", feedback_count=1, feedback_sum=5),
        _record(2, "high", feedback_count=3, feedback_sum=3),
    ]

    summary = summarize_usefulness(
        records, organizer_timezones={1: "UTC"}, range_start_date=date(2026, 1, 1), range_end_date=date(2026, 1, 31), now_utc=NOW
    )

    high = next(p for p in summary.by_priority if p.priority == "high")
    assert high.avg_score == 2.0
    assert high.rated_meeting_count == 2
    assert high.total_meeting_count == 2


def test_avg_score_is_none_not_zero_when_a_priority_has_no_ratings():
    records = [_record(1, "low", feedback_count=0, feedback_sum=0)]

    summary = summarize_usefulness(
        records, organizer_timezones={1: "UTC"}, range_start_date=date(2026, 1, 1), range_end_date=date(2026, 1, 31), now_utc=NOW
    )

    low = next(p for p in summary.by_priority if p.priority == "low")
    assert low.avg_score is None, "zero ratings must be None, not a misleading score of 0.0"
    assert low.total_meeting_count == 1
    assert low.rated_meeting_count == 0

    critical = next(p for p in summary.by_priority if p.priority == "critical")
    assert critical.total_meeting_count == 0
    assert critical.avg_score is None


def test_a_meeting_that_has_not_happened_yet_is_excluded_from_coverage():
    future = MeetingUsefulnessRecord(
        meeting_id=1,
        title="Future meeting",
        priority="high",
        organizer_id=1,
        organizer_name="Alice",
        start_utc="2026-01-05T10:00:00Z",
        end_utc="2026-01-05T10:30:00Z",
        feedback_count=0,
        feedback_sum=0,
    )
    # now_utc is BEFORE this meeting's end -- it hasn't happened yet
    now_before_meeting = datetime(2026, 1, 1, tzinfo=timezone.utc)

    summary = summarize_usefulness(
        [future],
        organizer_timezones={1: "UTC"},
        range_start_date=date(2026, 1, 1),
        range_end_date=date(2026, 1, 31),
        now_utc=now_before_meeting,
    )

    assert summary.coverage_eligible == 0, "a meeting that hasn't happened yet must not count as eligible for feedback"


def test_needs_attention_only_high_and_critical_sorted_ascending_by_score():
    records = [
        _record(1, "critical", feedback_count=2, feedback_sum=8),  # avg 4.0
        _record(2, "high", feedback_count=1, feedback_sum=1),  # avg 1.0
        _record(3, "low", feedback_count=1, feedback_sum=1),  # low priority -- excluded regardless of score
        _record(4, "critical", feedback_count=1, feedback_sum=2),  # avg 2.0
    ]

    summary = summarize_usefulness(
        records, organizer_timezones={1: "UTC"}, range_start_date=date(2026, 1, 1), range_end_date=date(2026, 1, 31), now_utc=NOW
    )

    assert [m.meeting_id for m in summary.needs_attention] == [2, 4, 1]
    assert all(m.priority in ("high", "critical") for m in summary.needs_attention)


def test_usefulness_range_filter_uses_the_organizers_own_local_date():
    # Same cross-midnight case as the meeting-time dashboard tests: UTC
    # Jan 4 19:00 is already Jan 5 in Asia/Kolkata (+5:30).
    record = MeetingUsefulnessRecord(
        meeting_id=1,
        title="Cross-midnight meeting",
        priority="medium",
        organizer_id=1,
        organizer_name="Priya",
        start_utc="2026-01-04T19:00:00Z",
        end_utc="2026-01-04T19:30:00Z",
        feedback_count=1,
        feedback_sum=4,
    )

    summary = summarize_usefulness(
        [record],
        organizer_timezones={1: "Asia/Kolkata"},
        range_start_date=date(2026, 1, 5),
        range_end_date=date(2026, 1, 5),
        now_utc=NOW,
    )

    medium = next(p for p in summary.by_priority if p.priority == "medium")
    assert medium.total_meeting_count == 1, "must count toward the organizer's local date (Jan 5), not UTC's (Jan 4)"


def test_cancelled_meetings_are_excluded_from_the_usefulness_fetch(conn):
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
        idempotency_key="usefulness-cancel-check",
        title="Will be cancelled",
        organizer_id=alice_id,
        start_utc="2026-01-05T10:00:00Z",
        end_utc="2026-01-05T11:00:00Z",
        created_at_utc="2026-01-01T00:00:00Z",
        participant_ids=[],
    )
    conn.execute("UPDATE meetings SET status = 'cancelled' WHERE id = ?", (meeting.id,))
    conn.commit()

    records = get_meeting_usefulness_in_utc_window(conn, "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")

    assert records == [], "a cancelled meeting must not appear in usefulness analytics"
