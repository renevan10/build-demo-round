"""Aggregates meeting time per employee, attributed to each employee's own
local calendar day -- not the server's or a shared UTC day.

Pure, no DB access: app/repository_dashboard.py fetches a UTC-bounded
superset of (employee, meeting) attendances; this module does the exact
per-employee timezone conversion SQLite can't do, then aggregates. Same
split as app/scheduling/slots.py + app/repository_scheduling.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.timeutil import to_user_local

_DAYS_PER_WEEK = 7
_DAYS_PER_MONTH = 30.44  # average Gregorian month length; fine for an average, not a bucket


@dataclass(frozen=True)
class MeetingAttendance:
    employee_id: int
    start_utc: str
    end_utc: str


@dataclass(frozen=True)
class EmployeeMeetingTime:
    employee_id: int
    employee_name: str
    meeting_count: int
    total_hours: float
    avg_hours_per_day: float
    avg_hours_per_week: float
    avg_hours_per_month: float


def summarize_meeting_time(
    attendances: list[MeetingAttendance],
    employee_timezones: dict[int, str],
    employee_names: dict[int, str],
    range_start_date: date,
    range_end_date: date,
) -> list[EmployeeMeetingTime]:
    """Every employee in employee_timezones appears in the result, even
    with zero meetings -- sparse is a real case, not an omission.

    An attendance counts toward an employee's total only if THEIR OWN
    local date (converted from the meeting's start_utc via their own
    timezone) falls inside [range_start_date, range_end_date]. Two
    attendees of the same meeting can land it in different local dates
    near a day boundary -- that's correct, not a bug: it's the same
    reasoning that keeps this app from ever billing/reporting off a
    shared UTC date. The day-count denominator (for the per-day/week/
    month averages) is the same for every employee, though -- it's the
    requested reporting period's length, not anything timezone-dependent.
    """
    days_in_range = (range_end_date - range_start_date).days + 1
    if days_in_range <= 0:
        raise ValueError("range_end_date must not be before range_start_date")

    minutes_by_employee: dict[int, float] = {eid: 0.0 for eid in employee_timezones}
    count_by_employee: dict[int, int] = {eid: 0 for eid in employee_timezones}

    for attendance in attendances:
        tz = employee_timezones.get(attendance.employee_id)
        if tz is None:
            continue
        start_dt = _parse_z(attendance.start_utc)
        end_dt = _parse_z(attendance.end_utc)
        local_date = to_user_local(start_dt, tz).date()
        if not (range_start_date <= local_date <= range_end_date):
            continue
        minutes_by_employee[attendance.employee_id] += (end_dt - start_dt).total_seconds() / 60
        count_by_employee[attendance.employee_id] += 1

    weeks_in_range = days_in_range / _DAYS_PER_WEEK
    months_in_range = days_in_range / _DAYS_PER_MONTH

    results = [
        EmployeeMeetingTime(
            employee_id=eid,
            employee_name=employee_names.get(eid, f"#{eid}"),
            meeting_count=count_by_employee[eid],
            total_hours=round(minutes / 60, 2),
            avg_hours_per_day=round(minutes / 60 / days_in_range, 2),
            avg_hours_per_week=round(minutes / 60 / weeks_in_range, 2),
            avg_hours_per_month=round(minutes / 60 / months_in_range, 2),
        )
        for eid, minutes in minutes_by_employee.items()
    ]
    results.sort(key=lambda r: r.total_hours, reverse=True)
    return results


def _parse_z(instant_z: str) -> datetime:
    return datetime.fromisoformat(instant_z.replace("Z", "+00:00"))
