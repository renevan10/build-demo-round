-- Demo table only, to back the patterns in app/repository_example.py.
-- Delete this table (and that file) once you're building the real schema —
-- keep the migration-runner convention, not this content.

CREATE TABLE IF NOT EXISTS demo_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_demo_events_created_at ON demo_events (created_at_utc);
