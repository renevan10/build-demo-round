# Design — meeting scheduler with usefulness-driven prioritization

Planning-session material for the Build & Demo round. This describes the
actual project being built, not a hypothetical — the status markers below
reflect real progress, not a plan.

## What this is

A meeting scheduler for a company with employees spread across timezones
and offices. Employees pick who's invited and book a room (or go virtual);
the system prevents double-booking a room. Every meeting carries a
priority. After a meeting ends, invited employees can rate how useful it
was — that usefulness score is the differentiator: it's meant to feed back
into how future meetings from the same organizer/type get prioritized, not
just sit in a table unread. A dashboard shows both sides of the same
story: how much time people are actually spending in meetings (daily
average, weekly, monthly), and which of that time was worth it.

## Scope, in build order

1. **Data model + adversarial mock data** — offices, employees, rooms,
   meetings, participants, priority, usefulness feedback. **Done** — see
   `migrations/0001_init.sql`, `app/repository_meetings.py`,
   `fixtures/seed_data.py`.
2. **Working frontend, CRUD-first** — schedule a meeting by selecting
   employees + a room; view a single employee's schedule; view the list of
   all meetings. No ranking/optimization yet — this proves the plumbing
   works end to end before anything gets smarter. *Not started.*
3. **Prioritization + dashboards** — once #2 works, layer on:
   - Time-in-meetings dashboard: per employee/team, aggregated by day
     (average), week, and month.
   - Usefulness dashboard: average usefulness by priority level, by
     organizer, by meeting — surfacing the "expensive but not useful"
     pattern the seed data already has an example of
     (`seed-critical-low-value`, the inverse case is `seed-low-priority-high-value`).
   - Feed usefulness scores back into priority: a simple, explainable
     version is "flag recurring meetings whose last N usefulness scores
     are low" rather than a learned model — keep it demoable and defensible
     in two hours.

   *Not started.*

Stretch, only if time remains after #3: rank candidate meeting times by an
inconvenience *cost* instead of a plain "everyone's free" filter, so a
meeting doesn't get scheduled by dumping all the pain on whoever's in the
worst timezone. Interesting, but not the differentiator anymore — the
usefulness feedback loop is. Kept as an appendix below in case there's
time for it.

## Data model (as built)

- `offices(id, name, city, timezone)`
- `employees(id, name, email, timezone, office_id)` — an employee's own
  timezone can differ from their office's (remote/travel)
- `meeting_rooms(id, office_id, name, capacity)`
- `working_hours(employee_id, day_of_week, start_local, end_local)` — ISO
  day-of-week (1=Mon..7=Sun), so a Sunday–Thursday work week is just a
  different set of rows, not a special case
- `blackouts(employee_id, local_date, reason)` — a **local calendar date**,
  converted to a UTC range via the employee's own timezone at query time
- `meetings(id, title, organizer_id, start_utc, end_utc, room_id NULL,
  priority, status, idempotency_key UNIQUE, created_at_utc)`
- `meeting_participants(meeting_id, employee_id, attendance_role)`
- `meeting_feedback(meeting_id, employee_id, usefulness_score 1–5,
  submitted_at_utc)` — composite FK against `meeting_participants`, so only
  an actual invitee can rate a meeting

Full detail and rationale: `migrations/0001_init.sql`.

## Adversarial dataset (seeded)

`fixtures/seed_data.py` — run with `python -m fixtures.seed_data`:

- Employee at **+5:30** (India) — breaks any code that assumes whole-hour
  UTC offsets
- A meeting sitting exactly on the **US DST transition instant**
  (2026-03-08) — fixed-offset math would place it an hour off
- **Back-to-back room bookings** (B starts exactly when A ends) — proves
  the overlap check is half-open, not an off-by-one false conflict
- An employee whose work week is **Sunday–Thursday**, not Mon–Fri
- An employee whose **personal timezone differs from their office's**
  (remote worker)
- A **blackout** on a local calendar date — catches naive UTC-date
  conversion
- A **critical-priority meeting rated low** and a **low-priority meeting
  rated high** — proof the dashboard can't just assume priority and
  usefulness correlate

Still to hand-author once the frontend/dashboard work starts: a room
booked past capacity (more required attendees than the room holds — not
enforced anywhere yet), and a completed meeting with zero feedback
submitted (the sparse case for the usefulness dashboard).

## Guardrails already proven by tests (`tests/test_guardrails.py`)

- Duplicate idempotency key rejected via a UNIQUE constraint, not
  check-then-insert
- Room double-booking rejected via `BEGIN IMMEDIATE` + an overlap query —
  see why `app/db.py::connect` sets `isolation_level=None` (Python's
  `sqlite3` otherwise opens an implicit transaction that collides with the
  explicit one)
- Feedback from a non-participant rejected at the DB level (composite FK)
- Employee-schedule pagination is SQL-side, not a Python slice
- The full adversarial seed set loads without violating any constraint

## Cheat-sheet answers, pre-written

- **QPS/scale**: low-volume, correctness-bound, not throughput-bound for a
  single company's meeting load. Say that explicitly rather than forcing a
  scaling story that doesn't fit.
- **Locking/isolation**: room booking is the one write that matters —
  `BEGIN IMMEDIATE` acquires SQLite's single write lock before the overlap
  check runs, so the check-then-insert has no gap for a second writer to
  land in. Meeting creation's idempotency is a UNIQUE constraint doing the
  serialization, not app-level locking.

## API surface (sketch, for the frontend phase)

- `POST /offices`, `POST /employees`, `POST /meeting-rooms`
- `POST /meetings` — `{title, organizer_id, participant_ids, room_id?,
  start_utc, end_utc, priority, idempotency_key}` → the created meeting, or
  a 409 on room conflict
- `GET /employees/{id}/schedule` — paginated list of that employee's
  meetings
- `GET /meetings` — paginated list of all meetings
- `POST /meetings/{id}/feedback` — `{employee_id, usefulness_score}`,
  rejected for non-participants and for meetings not yet `completed`
- `GET /dashboard/time-in-meetings` — per employee/team, day/week/month
- `GET /dashboard/usefulness` — average score by priority/organizer

## Appendix: fairness-cost slot ranking (stretch, not started)

The original hook for this idea before the plan broadened: given
participants across timezones with working-hour constraints, don't just
filter down to "everyone's free" — rank candidate slots by an
inconvenience *cost*, specifically avoiding the trap of minimizing total
cost while dumping all the pain on one person.

Four small pure functions, `app/scheduling/slots.py`:

1. `generate_candidate_slots(search_start_utc, search_end_utc, duration, granularity)`
   — candidate start times in UTC
2. `is_within_working_hours(slot, employee)` — converts slot boundaries to
   the employee's local time and checks against *that day's* window (a slot
   can straddle two local calendar days near midnight — check both)
3. `inconvenience_cost(slot, employee)` — 0 inside core hours, ramps
   outside, effectively infinite outside an absolute limit
4. `rank_slots(slots, employees)` — sorts by `(feasible, total_cost,
   max_cost)`; the `max_cost` tiebreak is the fairness mechanism, not an
   afterthought

Only worth building if #2 and #3 above are solid with time to spare.
