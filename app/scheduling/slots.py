"""Pure functions for ranking candidate meeting times by inconvenience
*cost* instead of a plain "everyone's free" filter -- and specifically
avoiding the trap of minimizing total cost while dumping all the pain on
one person (the `max_cost` tiebreak in rank_slots).

No DB access here on purpose: everything an EmployeeContext needs is
fetched in one batch per request by app/repository_scheduling.py, so this
module stays pure and independently testable. Two-tier constraint model:

- HARD infeasible (a candidate slot is dropped entirely): an existing
  meeting conflict, or a blackout date. These are "literally cannot
  attend," not "would rather not."
- SOFT cost (ranked, never filtered): distance outside normal working
  hours, calendar fragmentation, and how meeting-heavy that day already
  is. Working hours are cost, not a hard filter, on purpose -- a hard
  filter would make most cross-timezone meetings infeasible outright,
  which defeats the point of a *fairness* ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.timeutil import to_user_local, to_utc_z, user_local_date_str

_NO_WORKING_DAY_COST = 240.0
_MAX_HOURS_COST = 300.0
_PER_MINUTE_OUTSIDE = 1.0
_FRAGMENT_GAP_MINUTES = 30
_FRAGMENT_PENALTY = 15.0
_LOAD_PER_MINUTE = 0.15
_MAX_LOAD_COST = 120.0


@dataclass(frozen=True)
class EmployeeContext:
    employee_id: int
    timezone: str
    working_hours: dict[int, tuple[str, str]]  # ISO day_of_week (1=Mon..7=Sun) -> (start_local, end_local) "HH:MM"
    blackout_local_dates: frozenset[str]  # "YYYY-MM-DD"
    busy_intervals_utc: tuple[tuple[str, str], ...]  # existing meetings, "...Z" strings
    usefulness_weight: float = 1.0  # >1 = protect their convenience more, <1 = less; see repository_scheduling.py


@dataclass(frozen=True)
class SlotCost:
    employee_id: int
    cost: float


@dataclass(frozen=True)
class RankedSlot:
    start_utc: datetime
    end_utc: datetime
    total_cost: float
    max_cost: float
    required_costs: tuple[SlotCost, ...]
    optional_costs: tuple[SlotCost, ...]


def generate_candidate_slots(
    search_start_utc: datetime,
    search_end_utc: datetime,
    duration_minutes: int,
    granularity_minutes: int = 30,
) -> list[tuple[datetime, datetime]]:
    """Candidate (start, end) pairs in UTC, every granularity_minutes, each
    fully inside [search_start_utc, search_end_utc)."""
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    step = timedelta(minutes=granularity_minutes)
    duration = timedelta(minutes=duration_minutes)
    slots = []
    cursor = search_start_utc
    while cursor + duration <= search_end_utc:
        slots.append((cursor, cursor + duration))
        cursor += step
    return slots


def _parse_z(instant_z: str) -> datetime:
    return datetime.fromisoformat(instant_z.replace("Z", "+00:00"))


def is_blacked_out(slot_start_utc: datetime, slot_end_utc: datetime, ctx: EmployeeContext) -> bool:
    local_start = to_user_local(slot_start_utc, ctx.timezone)
    local_end = to_user_local(slot_end_utc, ctx.timezone)
    touched = {local_start.date().isoformat(), local_end.date().isoformat()}
    return not touched.isdisjoint(ctx.blackout_local_dates)


def has_conflict(slot_start_utc: datetime, slot_end_utc: datetime, ctx: EmployeeContext) -> bool:
    """Standard interval-intersection, half-open on `end` -- a meeting
    ending exactly when the slot starts does NOT conflict, matching the
    room-booking overlap check in app/repository_meetings.py."""
    start_z = to_utc_z(slot_start_utc)
    end_z = to_utc_z(slot_end_utc)
    return any(busy_start < end_z and busy_end > start_z for busy_start, busy_end in ctx.busy_intervals_utc)


def _hours_cost(local_start: datetime, local_end: datetime, working_hours: dict[int, tuple[str, str]]) -> float:
    if local_start.date() != local_end.date():
        # A slot straddling a local midnight can't fit inside a single
        # day's window in this data model -- max out rather than silently
        # checking only the start day's window.
        return _MAX_HOURS_COST

    window = working_hours.get(local_start.isoweekday())
    if window is None:
        return _NO_WORKING_DAY_COST

    window_start = _hhmm_to_minutes(window[0])
    window_end = _hhmm_to_minutes(window[1])
    slot_start = local_start.hour * 60 + local_start.minute
    slot_end = local_end.hour * 60 + local_end.minute

    before = max(0, window_start - slot_start)
    after = max(0, slot_end - window_end)
    return min(_MAX_HOURS_COST, (before + after) * _PER_MINUTE_OUTSIDE)


def _hhmm_to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _fragmentation_cost(slot_start_utc: datetime, slot_end_utc: datetime, busy_intervals_utc: tuple[tuple[str, str], ...]) -> float:
    """Penalize a slot that leaves a short, awkward-to-use gap next to an
    existing meeting. A slot sitting flush against one (gap == 0, i.e.
    back-to-back) is NOT penalized -- only an orphan gap too short to be
    useful free time."""
    start_z = to_utc_z(slot_start_utc)
    end_z = to_utc_z(slot_end_utc)
    penalty = 0.0
    for busy_start, busy_end in busy_intervals_utc:
        if busy_end <= start_z:
            gap = (slot_start_utc - _parse_z(busy_end)).total_seconds() / 60
            if 0 < gap < _FRAGMENT_GAP_MINUTES:
                penalty += _FRAGMENT_PENALTY
        if busy_start >= end_z:
            gap = (_parse_z(busy_start) - slot_end_utc).total_seconds() / 60
            if 0 < gap < _FRAGMENT_GAP_MINUTES:
                penalty += _FRAGMENT_PENALTY
    return penalty


def _daily_load_cost(slot_start_utc: datetime, ctx: EmployeeContext) -> float:
    """The more of this local day is already booked, the more it costs to
    add one more meeting to it -- spreads load instead of stacking it."""
    target_date = user_local_date_str(slot_start_utc, ctx.timezone)
    existing_minutes = 0.0
    for busy_start, busy_end in ctx.busy_intervals_utc:
        start_dt = _parse_z(busy_start)
        if user_local_date_str(start_dt, ctx.timezone) == target_date:
            existing_minutes += (_parse_z(busy_end) - start_dt).total_seconds() / 60
    return min(_MAX_LOAD_COST, existing_minutes * _LOAD_PER_MINUTE)


def inconvenience_cost(slot_start_utc: datetime, slot_end_utc: datetime, ctx: EmployeeContext) -> float:
    local_start = to_user_local(slot_start_utc, ctx.timezone)
    local_end = to_user_local(slot_end_utc, ctx.timezone)
    raw = (
        _hours_cost(local_start, local_end, ctx.working_hours)
        + _fragmentation_cost(slot_start_utc, slot_end_utc, ctx.busy_intervals_utc)
        + _daily_load_cost(slot_start_utc, ctx)
    )
    return raw * ctx.usefulness_weight


def rank_slots(
    candidate_slots: list[tuple[datetime, datetime]],
    required: list[EmployeeContext],
    optional: list[EmployeeContext],
) -> list[RankedSlot]:
    """Drop slots infeasible for any required attendee; rank the rest by
    (total_cost, max_cost) -- the max_cost tiebreak is the fairness
    mechanism: between two slots with equal total pain, prefer the one
    that doesn't dump it all on one person. Optional attendees who are
    busy/blacked-out at a slot are simply excluded from that slot's cost,
    never made to block it."""
    ranked = []
    for slot_start, slot_end in candidate_slots:
        if any(
            has_conflict(slot_start, slot_end, ctx) or is_blacked_out(slot_start, slot_end, ctx)
            for ctx in required
        ):
            continue

        required_costs = tuple(
            SlotCost(ctx.employee_id, inconvenience_cost(slot_start, slot_end, ctx)) for ctx in required
        )
        available_optional = [
            ctx
            for ctx in optional
            if not has_conflict(slot_start, slot_end, ctx) and not is_blacked_out(slot_start, slot_end, ctx)
        ]
        optional_costs = tuple(
            SlotCost(ctx.employee_id, inconvenience_cost(slot_start, slot_end, ctx)) for ctx in available_optional
        )

        total_cost = sum(c.cost for c in required_costs) + sum(c.cost for c in optional_costs)
        max_cost = max((c.cost for c in required_costs), default=0.0)
        ranked.append(RankedSlot(slot_start, slot_end, total_cost, max_cost, required_costs, optional_costs))

    ranked.sort(key=lambda r: (r.total_cost, r.max_cost, r.start_utc))
    return ranked
