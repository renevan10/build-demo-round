-- Real domain schema for the meeting scheduler (replaces the scaffold's
-- demo_events placeholder now that the idea is locked in).

CREATE TABLE IF NOT EXISTS offices (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    city     TEXT NOT NULL,
    timezone TEXT NOT NULL  -- IANA name, e.g. "America/New_York"
);

CREATE TABLE IF NOT EXISTS employees (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    email     TEXT NOT NULL UNIQUE,
    timezone  TEXT NOT NULL,  -- IANA name; can differ from their office's (remote/travel)
    office_id INTEGER NOT NULL REFERENCES offices(id)
);

CREATE INDEX IF NOT EXISTS idx_employees_office ON employees (office_id);

CREATE TABLE IF NOT EXISTS meeting_rooms (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    office_id INTEGER NOT NULL REFERENCES offices(id),
    name      TEXT NOT NULL,
    capacity  INTEGER NOT NULL CHECK (capacity > 0),
    UNIQUE (office_id, name)
);

-- One contiguous window per employee per weekday. day_of_week is ISO
-- (1=Monday .. 7=Sunday, matches Python's date.isoweekday()) specifically so
-- a Sunday-Thursday work week is just rows {7,1,2,3,4} -- no special case.
CREATE TABLE IF NOT EXISTS working_hours (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    start_local TEXT NOT NULL,  -- "HH:MM", the employee's own local wall-clock time
    end_local   TEXT NOT NULL,
    PRIMARY KEY (employee_id, day_of_week),
    CHECK (start_local < end_local)
);

CREATE TABLE IF NOT EXISTS blackouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    local_date  TEXT NOT NULL,  -- YYYY-MM-DD in the employee's own timezone
    reason      TEXT,
    UNIQUE (employee_id, local_date)
);

CREATE TABLE IF NOT EXISTS meetings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    organizer_id    INTEGER NOT NULL REFERENCES employees(id),
    start_utc       TEXT NOT NULL,
    end_utc         TEXT NOT NULL,
    room_id         INTEGER REFERENCES meeting_rooms(id),  -- NULL = virtual, no room
    priority        TEXT NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled', 'cancelled', 'completed')),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at_utc  TEXT NOT NULL,
    CHECK (end_utc > start_utc)
);

-- Backs the room-conflict check in app/repository_meetings.py. Partial index:
-- virtual meetings (room_id IS NULL) never need an overlap scan.
CREATE INDEX IF NOT EXISTS idx_meetings_room_time
    ON meetings (room_id, start_utc, end_utc)
    WHERE room_id IS NOT NULL;

-- Backs dashboard time-range aggregation (per week/month/day).
CREATE INDEX IF NOT EXISTS idx_meetings_start_utc ON meetings (start_utc);

CREATE TABLE IF NOT EXISTS meeting_participants (
    meeting_id      INTEGER NOT NULL REFERENCES meetings(id),
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    attendance_role TEXT NOT NULL DEFAULT 'required'
                        CHECK (attendance_role IN ('required', 'optional')),
    PRIMARY KEY (meeting_id, employee_id)
);

-- Backs "this employee's schedule" and the dashboard's per-employee
-- time-in-meetings aggregation.
CREATE INDEX IF NOT EXISTS idx_meeting_participants_employee
    ON meeting_participants (employee_id);

CREATE TABLE IF NOT EXISTS meeting_feedback (
    meeting_id       INTEGER NOT NULL,
    employee_id      INTEGER NOT NULL,
    usefulness_score INTEGER NOT NULL CHECK (usefulness_score BETWEEN 1 AND 5),
    submitted_at_utc TEXT NOT NULL,
    PRIMARY KEY (meeting_id, employee_id),
    -- Composite FK targets meeting_participants, not meetings: "you can only
    -- rate a meeting you were actually invited to" becomes a DB-enforced
    -- invariant instead of an application check that's easy to forget.
    FOREIGN KEY (meeting_id, employee_id)
        REFERENCES meeting_participants (meeting_id, employee_id)
);
