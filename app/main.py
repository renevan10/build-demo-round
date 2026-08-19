"""FastAPI app: directory lookups + meeting scheduling, wired to the DB."""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from typing import Iterator, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

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
    DuplicateMeetingError,
    Meeting,
    MeetingSummary,
    RoomConflictError,
    create_meeting_idempotent,
    list_employee_schedule_with_details,
    list_meetings_with_details,
)
from app.timeutil import local_wall_clock_to_utc, to_utc_z, utc_now

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
    room_id: int | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    local_start: str  # "YYYY-MM-DDTHH:MM", wall-clock time in `timezone`
    local_end: str
    timezone: str
    idempotency_key: str


@app.post("/api/meetings", status_code=201)
def post_meeting(body: MeetingCreateRequest) -> Meeting:
    try:
        start_utc = local_wall_clock_to_utc(body.local_start, body.timezone)
        end_utc = local_wall_clock_to_utc(body.local_end, body.timezone)
    except (ValueError, KeyError) as exc:
        # KeyError is what ZoneInfo raises for an unknown IANA name.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if end_utc <= start_utc:
        raise HTTPException(status_code=400, detail="end must be after start")

    try:
        with db() as conn:
            return create_meeting_idempotent(
                conn,
                idempotency_key=body.idempotency_key,
                title=body.title,
                organizer_id=body.organizer_id,
                start_utc=to_utc_z(start_utc),
                end_utc=to_utc_z(end_utc),
                created_at_utc=to_utc_z(utc_now()),
                participant_ids=body.participant_ids,
                room_id=body.room_id,
                priority=body.priority,
            )
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
