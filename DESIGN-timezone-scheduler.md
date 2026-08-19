# Design sketch — timezone-fair meeting scheduler

Planning-session material for the Build & Demo round. Nothing here is built
yet — the DB still only has the scaffold's placeholder table
(`migrations/0001_init.sql` → `demo_events`). This doc is the plan to execute
against once the actual 2-hour window starts.

## Core idea

Given participants across timezones with working-hour constraints, don't
just filter down to "everyone's free" — rank candidate slots by an
inconvenience _cost_, and specifically avoid the naive trap of minimizing
total cost while dumping all the pain on one person. The fairness angle is
the "real value beyond the obvious" hook, same spirit as the brief's own
flight-ranking example. Booking rooms, analysis or dashboard on people and how much they spent on meetings. Conflict management, prevent same room from being booked during concurrent requests. Importance on meetings. Feedback on usefulness of meetings, to prioritize which person's availability to prioritize over the other.

## Data model (SQLite)

- `participants(id, name, timezone, role)` — role is `must` or `optional`
- `working_hours(participant_id, day_of_week, start_local, end_local)` —
  per-day, not one fixed Mon–Fri window
- `blackouts(participant_id, local_date, reason)` — stored as a **local
  calendar date**, converted to a UTC range via the participant's own
  timezone at query time. This is where the scaffold's `timeutil.py` gets a
  real second function: `local_date_bounds_utc(date, tz)`, the inverse of
  what's there now.
- `meeting_requests(id, idempotency_key UNIQUE, duration_minutes,
search_start_utc, search_end_utc, chosen_slot_utc, created_at_utc)` —
  persisting the request (not just computing on the fly) reuses the
  scaffold's idempotency pattern for something real: double-submitting the
  same request returns the same result instead of a duplicate.

## Core engine — build this first, reuse it for everything after

`app/scheduling/slots.py`, four small pure functions:

1. `generate_candidate_slots(search_start_utc, search_end_utc, duration, granularity)`
   — candidate start times in UTC
2. `is_within_working_hours(slot, participant)` — converts slot boundaries to
   the participant's local time and checks against _that day's_ window (a
   slot can straddle two local calendar days near midnight — check both)
3. `inconvenience_cost(slot, participant)` — 0 inside core hours, ramps
   outside, effectively infinite outside an absolute limit
4. `rank_slots(slots, participants)` — sorts by `(feasible, total_cost,
max_cost)`; the `max_cost` tiebreak is the fairness mechanism, not an
   afterthought

Phase 0 uses only #1–#2 (hard filter, binary works/doesn't). Everything
after layers onto the same functions instead of rewriting them.

## Adversarial dataset — hand-author these, don't happy-path it

- A participant at **+5:30** (India) — breaks any code that assumes
  whole-hour offsets
- Search window **spanning a DST transition** (e.g. includes 2026-03-08) —
  a participant's UTC offset changes mid-window, so a single fixed offset
  for the whole search is wrong
- **No feasible slot exists** for the must-attend set — must return "no
  valid slot," not crash or silently return garbage
- A **blackout exactly covering** the otherwise-best slot — forces
  fallback, tests blackout precedence over scoring
- **Two slots with equal total cost, different distribution** — one
  spreads inconvenience, one dumps it on one person — the test that catches
  a naive `sum()`-only implementation
- **Sparse window**: only 1–2 valid days left before the deadline — the
  "sparse routes" analog
- A participant whose work week is **Sunday–Thursday**, not Mon–Fri
- A request **exactly at a window boundary** (9:00:00 sharp) — `>=` vs `>`
  off-by-one

## Phasing (2-hour budget)

| Time      | Milestone                                                                                                   |
| --------- | ----------------------------------------------------------------------------------------------------------- |
| 0:00–0:20 | Copy scaffold, schema/migrations, seed script with the adversarial dataset above                            |
| 0:20–0:50 | Core engine (#1–#2 only), hard-filter end-to-end via `POST /schedule`, tests for the DST and boundary cases |
| 0:50–1:20 | Add `inconvenience_cost` + fairness ranking, test the equal-total/unequal-distribution case                 |
| 1:20–1:45 | Blackouts + idempotent `meeting_requests` (reuses the scaffold's unique-constraint pattern)                 |
| 1:45–2:00 | Run the full adversarial set live, polish output, final commits                                             |

## Cheat-sheet answers, pre-written

- **QPS/scale**: this domain doesn't really have one — it's low-volume,
  correctness-bound, not throughput-bound. Say that explicitly rather than
  forcing a scaling story that doesn't fit.
- **Locking/isolation**: the only write is the idempotent insert on
  `meeting_requests`, protected by the unique constraint on
  `idempotency_key`. Blackout/participant writes never mutate existing
  rows, so there's no concurrent-update race to reason about.

## API surface (sketch)

- `POST /participants` — create participant (name, timezone, role)
- `POST /participants/{id}/working-hours` — set per-day windows
- `POST /participants/{id}/blackouts` — add a blackout local date
- `POST /schedule` — `{participant_ids, duration_minutes, search_start_utc,
search_end_utc, idempotency_key}` → ranked slots with per-participant
  local times, costs, and a feasibility flag
- `GET /participants` — paginated list (reuses `list_paginated` pattern)
