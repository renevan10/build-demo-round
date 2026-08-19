"""DB access for the dashboard (meeting-time and usefulness sections).

Fetches a UTC-bounded superset -- SQL can filter on a UTC range (index-
backed on start_utc), but it can't do the IANA timezone conversion needed
to know which employee-local calendar day a meeting actually falls on.
That precise filtering happens in app/dashboard.py; this just gets the
candidate rows cheaply.
"""

from __future__ import annotations

import sqlite3

from app.dashboard import MeetingAttendance, MeetingUsefulnessRecord


def get_attendances_in_utc_window(
    conn: sqlite3.Connection, window_start_utc: str, window_end_utc: str
) -> list[MeetingAttendance]:
    rows = conn.execute(
        "SELECT mp.employee_id, m.start_utc, m.end_utc "
        "FROM meetings m "
        "JOIN meeting_participants mp ON mp.meeting_id = m.id "
        "WHERE m.status != 'cancelled' AND m.start_utc < ? AND m.end_utc > ? "
        "ORDER BY m.start_utc",
        (window_end_utc, window_start_utc),
    ).fetchall()
    return [MeetingAttendance(row["employee_id"], row["start_utc"], row["end_utc"]) for row in rows]


def get_meeting_usefulness_in_utc_window(
    conn: sqlite3.Connection, window_start_utc: str, window_end_utc: str
) -> list[MeetingUsefulnessRecord]:
    """One row per meeting (not per feedback row), with the feedback count
    and score sum pre-aggregated -- so app/dashboard.py can re-aggregate by
    priority/organizer with a correct weighted average (sum of sums over
    sum of counts), not an average-of-per-meeting-averages, which would
    silently over-weight meetings with fewer raters."""
    rows = conn.execute(
        "SELECT m.id, m.title, m.priority, m.organizer_id, o.name AS organizer_name, "
        "       m.start_utc, m.end_utc, "
        "       COUNT(mf.usefulness_score) AS feedback_count, "
        "       COALESCE(SUM(mf.usefulness_score), 0) AS feedback_sum "
        "FROM meetings m "
        "JOIN employees o ON o.id = m.organizer_id "
        "LEFT JOIN meeting_feedback mf ON mf.meeting_id = m.id "
        "WHERE m.status != 'cancelled' AND m.start_utc >= ? AND m.start_utc < ? "
        "GROUP BY m.id",
        (window_start_utc, window_end_utc),
    ).fetchall()
    return [
        MeetingUsefulnessRecord(
            meeting_id=row["id"],
            title=row["title"],
            priority=row["priority"],
            organizer_id=row["organizer_id"],
            organizer_name=row["organizer_name"],
            start_utc=row["start_utc"],
            end_utc=row["end_utc"],
            feedback_count=row["feedback_count"],
            feedback_sum=row["feedback_sum"],
        )
        for row in rows
    ]
