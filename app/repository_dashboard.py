"""DB access for the meeting-time dashboard.

Fetches a UTC-bounded superset of (employee, meeting) attendances -- SQL
can filter on a UTC range (index-backed on start_utc), but it can't do the
IANA timezone conversion needed to know which employee-local calendar day
a meeting actually falls on. That precise filtering happens in
app/dashboard.py; this just gets the candidate rows cheaply.
"""

from __future__ import annotations

import sqlite3

from app.dashboard import MeetingAttendance


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
