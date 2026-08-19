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


_PRIORITY_ORDER = ["low", "medium", "high", "critical"]
_NEEDS_ATTENTION_PRIORITIES = {"high", "critical"}
_NEEDS_ATTENTION_LIMIT = 10


@dataclass(frozen=True)
class MeetingUsefulnessRecord:
    meeting_id: int
    title: str
    priority: str
    organizer_id: int
    organizer_name: str
    start_utc: str
    end_utc: str
    feedback_count: int
    feedback_sum: int


@dataclass(frozen=True)
class PriorityUsefulness:
    priority: str
    avg_score: float | None  # None means zero ratings, not a score of zero -- 1-5 scale, never actually 0
    rated_meeting_count: int
    total_meeting_count: int


@dataclass(frozen=True)
class OrganizerUsefulness:
    organizer_id: int
    organizer_name: str
    avg_score: float | None
    rated_meeting_count: int
    total_meeting_count: int


@dataclass(frozen=True)
class LowRatedMeeting:
    meeting_id: int
    title: str
    priority: str
    organizer_name: str
    avg_score: float
    feedback_count: int


@dataclass(frozen=True)
class UsefulnessSummary:
    coverage_rated: int
    coverage_eligible: int
    by_priority: list[PriorityUsefulness]
    by_organizer: list[OrganizerUsefulness]
    needs_attention: list[LowRatedMeeting]


def summarize_usefulness(
    records: list[MeetingUsefulnessRecord],
    organizer_timezones: dict[int, str],
    range_start_date: date,
    range_end_date: date,
    now_utc: datetime,
) -> UsefulnessSummary:
    """records should already exclude cancelled meetings (the repository
    query's job); this does the local-date range filter and aggregation.

    Filtered by the ORGANIZER's own local calendar day -- priority/
    organizer views don't have a single per-employee viewpoint the way
    the meeting-time dashboard's per-attendee view does, so the
    organizer (who every meeting has exactly one of) is the next most
    honest choice, not a shared UTC day.

    "Eligible for feedback" mirrors the actual submission gate in
    app/main.py: end_utc must be in the past. A meeting with zero
    feedback rows is a real, countable case (coverage), not an omission
    -- averaging would silently drop it instead of surfacing it.
    """
    in_range = [
        r
        for r in records
        if range_start_date
        <= to_user_local(_parse_z(r.start_utc), organizer_timezones.get(r.organizer_id, "UTC")).date()
        <= range_end_date
    ]
    eligible = [r for r in in_range if _parse_z(r.end_utc) < now_utc]
    rated = [r for r in eligible if r.feedback_count > 0]

    by_priority = [
        _aggregate_priority(priority, [r for r in eligible if r.priority == priority])
        for priority in _PRIORITY_ORDER
    ]

    organizer_names = {r.organizer_id: r.organizer_name for r in eligible}
    by_organizer = sorted(
        (
            _aggregate_organizer(oid, name, [r for r in eligible if r.organizer_id == oid])
            for oid, name in organizer_names.items()
        ),
        key=lambda o: (o.avg_score is None, o.avg_score if o.avg_score is not None else 0.0),
    )

    needs_attention = sorted(
        (
            LowRatedMeeting(
                meeting_id=r.meeting_id,
                title=r.title,
                priority=r.priority,
                organizer_name=r.organizer_name,
                avg_score=round(r.feedback_sum / r.feedback_count, 2),
                feedback_count=r.feedback_count,
            )
            for r in rated
            if r.priority in _NEEDS_ATTENTION_PRIORITIES
        ),
        key=lambda m: m.avg_score,
    )[:_NEEDS_ATTENTION_LIMIT]

    return UsefulnessSummary(
        coverage_rated=len(rated),
        coverage_eligible=len(eligible),
        by_priority=by_priority,
        by_organizer=by_organizer,
        needs_attention=needs_attention,
    )


def _avg_and_rated_count(records: list[MeetingUsefulnessRecord]) -> tuple[float | None, int]:
    total_score = sum(r.feedback_sum for r in records)
    total_scores = sum(r.feedback_count for r in records)
    rated_meetings = sum(1 for r in records if r.feedback_count > 0)
    avg = round(total_score / total_scores, 2) if total_scores > 0 else None
    return avg, rated_meetings


def _aggregate_priority(priority: str, records: list[MeetingUsefulnessRecord]) -> PriorityUsefulness:
    avg, rated = _avg_and_rated_count(records)
    return PriorityUsefulness(priority, avg, rated, len(records))


def _aggregate_organizer(
    organizer_id: int, organizer_name: str, records: list[MeetingUsefulnessRecord]
) -> OrganizerUsefulness:
    avg, rated = _avg_and_rated_count(records)
    return OrganizerUsefulness(organizer_id, organizer_name, avg, rated, len(records))
