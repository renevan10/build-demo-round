"""FastAPI app: directory lookups + meeting scheduling, wired to the DB."""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Iterator, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import connect, run_migrations
from app.repository_directory import (
    Employee,
    MeetingRoom,
    Office,
    list_employees,
    list_meeting_rooms,
    list_offices,
)
from app.repository_meetings import (
    BlackoutConflictError,
    DuplicateMeetingError,
    Meeting,
    MeetingSummary,
    PersonConflictError,
    RoomConflictError,
    create_meeting_idempotent,
    list_employee_schedule_with_details,
    list_meetings_with_details,
)
from app.dashboard import EmployeeMeetingTime, summarize_meeting_time
from app.repository_dashboard import get_attendances_in_utc_window
from app.repository_scheduling import build_employee_contexts
from app.scheduling.slots import generate_candidate_slots, rank_slots
from app.timeutil import local_wall_clock_to_utc, to_utc_z, utc_now

MAX_SEARCH_WINDOW = timedelta(days=14)
MAX_DASHBOARD_RANGE = timedelta(days=366)


def _parse_utc_z(instant_z: str) -> datetime:
    parsed = datetime.fromisoformat(instant_z.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{instant_z!r} is not a UTC instant")
    return parsed.astimezone(dt_timezone.utc)

DB_PATH = os.environ.get("APP_DB_PATH", "app.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect(DB_PATH)
    run_migrations(conn)
    conn.close()
    yield


app = FastAPI(lifespan=lifespan)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """A connection per request, opened and closed inside the endpoint's own
    function body -- not a FastAPI `Depends` generator.

    sqlite3 connections are bound to the thread that created them. A sync
    endpoint's whole body runs as one `run_in_threadpool` call on one
    thread, so `with db() as conn:` inside it is safe. A `Depends()`
    generator dependency is a *separate* `run_in_threadpool` call and is
    not guaranteed to land on that same thread -- it happened to work
    under light, sequential load and broke under a real browser's
    concurrent requests.
    """
    conn = connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---- Directory: offices, employees, rooms ----


@app.get("/api/offices")
def get_offices() -> list[Office]:
    with db() as conn:
        return list_offices(conn)


@app.get("/api/employees")
def get_employees() -> list[Employee]:
    with db() as conn:
        return list_employees(conn)


@app.get("/api/meeting-rooms")
def get_meeting_rooms(office_id: int | None = None) -> list[MeetingRoom]:
    with db() as conn:
        return list_meeting_rooms(conn, office_id=office_id)


# ---- Meetings ----


class MeetingCreateRequest(BaseModel):
    title: str
    organizer_id: int
    participant_ids: list[int] = []
    optional_participant_ids: list[int] = []
    room_id: int | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    local_start: str  # "YYYY-MM-DDTHH:MM", wall-clock time in `timezone`
    local_end: str
    timezone: str
    idempotency_key: str
    series_key: str | None = None


def _book_meeting_or_409(
    conn: sqlite3.Connection,
    *,
    start_utc,
    end_utc,
    idempotency_key: str,
    title: str,
    organizer_id: int,
    participant_ids: list[int],
    optional_participant_ids: list[int],
    room_id: int | None,
    priority: str,
    series_key: str | None,
) -> Meeting:
    """Shared by both booking entry points -- manual local-time entry and
    confirming a suggested (already-UTC) slot -- so the PersonConflictError/
    RoomConflictError/DuplicateMeetingError -> HTTPException mapping lives
    in one place."""
    if end_utc <= start_utc:
        raise HTTPException(status_code=400, detail="end must be after start")
    try:
        return create_meeting_idempotent(
            conn,
            idempotency_key=idempotency_key,
            title=title,
            organizer_id=organizer_id,
            start_utc=to_utc_z(start_utc),
            end_utc=to_utc_z(end_utc),
            created_at_utc=to_utc_z(utc_now()),
            participant_ids=participant_ids,
            optional_participant_ids=optional_participant_ids,
            room_id=room_id,
            priority=priority,
            series_key=series_key,
        )
    except BlackoutConflictError as exc:
        raise HTTPException(
            status_code=409, detail="A required attendee is unavailable (blacked out) on that date."
        ) from exc
    except PersonConflictError as exc:
        raise HTTPException(
            status_code=409, detail="A required attendee already has a conflicting meeting."
        ) from exc
    except RoomConflictError as exc:
        raise HTTPException(
            status_code=409, detail="That room is already booked for an overlapping time."
        ) from exc
    except DuplicateMeetingError as exc:
        raise HTTPException(
            status_code=409, detail="That meeting was already submitted."
        ) from exc
    except sqlite3.IntegrityError as exc:
        # Unknown organizer/participant/room id, or a CHECK violation that
        # slipped past validation above (belt and suspenders).
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/meetings", status_code=201)
def post_meeting(body: MeetingCreateRequest) -> Meeting:
    try:
        start_utc = local_wall_clock_to_utc(body.local_start, body.timezone)
        end_utc = local_wall_clock_to_utc(body.local_end, body.timezone)
    except (ValueError, KeyError) as exc:
        # KeyError is what ZoneInfo raises for an unknown IANA name.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db() as conn:
        return _book_meeting_or_409(
            conn,
            start_utc=start_utc,
            end_utc=end_utc,
            idempotency_key=body.idempotency_key,
            title=body.title,
            organizer_id=body.organizer_id,
            participant_ids=body.participant_ids,
            optional_participant_ids=body.optional_participant_ids,
            room_id=body.room_id,
            priority=body.priority,
            series_key=body.series_key,
        )


class BookSlotRequest(BaseModel):
    title: str
    organizer_id: int
    participant_ids: list[int] = []
    optional_participant_ids: list[int] = []
    room_id: int | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    start_utc: str  # already UTC -- as returned by POST /api/meetings/suggest
    end_utc: str
    idempotency_key: str
    series_key: str | None = None


@app.post("/api/meetings/book-slot", status_code=201)
def post_book_slot(body: BookSlotRequest) -> Meeting:
    try:
        start_utc = _parse_utc_z(body.start_utc)
        end_utc = _parse_utc_z(body.end_utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db() as conn:
        return _book_meeting_or_409(
            conn,
            start_utc=start_utc,
            end_utc=end_utc,
            idempotency_key=body.idempotency_key,
            title=body.title,
            organizer_id=body.organizer_id,
            participant_ids=body.participant_ids,
            optional_participant_ids=body.optional_participant_ids,
            room_id=body.room_id,
            priority=body.priority,
            series_key=body.series_key,
        )


class SuggestSlotsRequest(BaseModel):
    required_ids: list[int] = Field(..., min_length=1)
    optional_ids: list[int] = []
    duration_minutes: int = Field(..., gt=0, le=480)
    search_start_local: str  # "YYYY-MM-DDTHH:MM", wall-clock in `timezone`
    search_end_local: str
    timezone: str
    granularity_minutes: int = Field(30, ge=5, le=120)
    series_key: str | None = None
    max_results: int = Field(10, ge=1, le=50)


class SlotCostOut(BaseModel):
    employee_id: int
    employee_name: str
    cost: float


class RankedSlotOut(BaseModel):
    start_utc: str
    end_utc: str
    total_cost: float
    max_cost: float
    required_costs: list[SlotCostOut]
    optional_costs: list[SlotCostOut]


@app.post("/api/meetings/suggest")
def suggest_meeting_slots(body: SuggestSlotsRequest) -> list[RankedSlotOut]:
    try:
        search_start = local_wall_clock_to_utc(body.search_start_local, body.timezone)
        search_end = local_wall_clock_to_utc(body.search_end_local, body.timezone)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if search_end <= search_start:
        raise HTTPException(status_code=400, detail="search end must be after search start")
    if search_end - search_start > MAX_SEARCH_WINDOW:
        raise HTTPException(
            status_code=400, detail=f"search window can't exceed {MAX_SEARCH_WINDOW.days} days"
        )

    all_ids = list(dict.fromkeys(body.required_ids + body.optional_ids))

    with db() as conn:
        employees = list_employees(conn)
        timezone_by_id = {e.id: e.timezone for e in employees}
        name_by_id = {e.id: e.name for e in employees}
        unknown_ids = [eid for eid in all_ids if eid not in timezone_by_id]
        if unknown_ids:
            raise HTTPException(status_code=400, detail=f"unknown employee id(s): {unknown_ids}")

        contexts = build_employee_contexts(
            conn,
            all_ids,
            timezone_by_id,
            to_utc_z(search_start),
            to_utc_z(search_end),
            body.series_key,
        )

    required_contexts = [contexts[eid] for eid in body.required_ids]
    optional_contexts = [contexts[eid] for eid in body.optional_ids]

    candidates = generate_candidate_slots(
        search_start, search_end, body.duration_minutes, body.granularity_minutes
    )
    ranked = rank_slots(candidates, required_contexts, optional_contexts)

    def to_cost_out(costs) -> list[SlotCostOut]:
        return [
            SlotCostOut(employee_id=c.employee_id, employee_name=name_by_id[c.employee_id], cost=round(c.cost, 1))
            for c in costs
        ]

    return [
        RankedSlotOut(
            start_utc=to_utc_z(r.start_utc),
            end_utc=to_utc_z(r.end_utc),
            total_cost=round(r.total_cost, 1),
            max_cost=round(r.max_cost, 1),
            required_costs=to_cost_out(r.required_costs),
            optional_costs=to_cost_out(r.optional_costs),
        )
        for r in ranked[: body.max_results]
    ]


@app.get("/api/meetings")
def get_meetings(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> list[MeetingSummary]:
    with db() as conn:
        return list_meetings_with_details(conn, limit=limit, offset=offset)


@app.get("/api/employees/{employee_id}/schedule")
def get_employee_schedule(
    employee_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> list[MeetingSummary]:
    with db() as conn:
        return list_employee_schedule_with_details(conn, employee_id, limit=limit, offset=offset)


# ---- Dashboard ----


@app.get("/api/dashboard/meeting-time")
def get_meeting_time_dashboard(start_date: str, end_date: str) -> list[EmployeeMeetingTime]:
    try:
        range_start = date.fromisoformat(start_date)
        range_end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if range_end < range_start:
        raise HTTPException(status_code=400, detail="end_date must not be before start_date")
    if range_end - range_start > MAX_DASHBOARD_RANGE:
        raise HTTPException(
            status_code=400, detail=f"range can't exceed {MAX_DASHBOARD_RANGE.days} days"
        )

    # Pad the UTC fetch window by a day on each side: a meeting near the
    # edge of the requested range can land in-range for an employee whose
    # local date differs from UTC's (the exact naive-UTC-date bug this
    # project's guardrails exist to catch). app/dashboard.py re-filters
    # precisely per employee using their own timezone.
    window_start = datetime(range_start.year, range_start.month, range_start.day, tzinfo=dt_timezone.utc) - timedelta(
        days=1
    )
    window_end = datetime(
        range_end.year, range_end.month, range_end.day, tzinfo=dt_timezone.utc
    ) + timedelta(days=2)

    with db() as conn:
        employees = list_employees(conn)
        attendances = get_attendances_in_utc_window(conn, to_utc_z(window_start), to_utc_z(window_end))

    timezone_by_id = {e.id: e.timezone for e in employees}
    name_by_id = {e.id: e.name for e in employees}

    return summarize_meeting_time(attendances, timezone_by_id, name_by_id, range_start, range_end)
