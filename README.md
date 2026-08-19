# Build & Demo round — reusable scaffold

Not a project. This is the idea-agnostic skeleton you drop a chosen idea into
once the planning session picks one, so the first 20 minutes of the real
2-hour window aren't spent wiring up SQLite and a test runner.

## What's here

| Path | What it is |
|---|---|
| `app/db.py` | SQLite connection (WAL, foreign keys on) + a tiny migration runner |
| `app/timeutil.py` | Timezone-safe time helpers — explicit tz in, never the server clock |
| `app/repository_meetings.py` | Meeting creation/lookup: DB-level unique constraint instead of check-then-insert, `BEGIN IMMEDIATE` + overlap queries for race-safe room/person/blackout conflict checks, and SQL-side pagination instead of loading every row into memory |
| `app/scheduling/slots.py` | Pure cost/ranking engine behind "Find a time" — see [How meeting cost is calculated](#how-meeting-cost-is-calculated) below |
| `app/repository_scheduling.py` | Batches the working-hours/blackout/busy-interval/usefulness-history lookups the ranking engine needs, one query per source per request |
| `app/dashboard.py` / `app/repository_dashboard.py` | Meeting-time-per-employee aggregation, attributed to each employee's own local calendar day, not a shared UTC day |
| `app/main.py` | FastAPI app: directory lookups, meeting scheduling/suggestion, the dashboard endpoint |
| `migrations/*.sql` | Real schema: offices, employees, meeting rooms, meetings, participants, working hours, blackouts, usefulness feedback, and a lightweight `series_key` for tying feedback to future scheduling |
| `tests/` | Pytest harness with fixtures; `test_guardrails.py`, `test_scheduling_slots.py`, and `test_dashboard.py` prove the patterns above actually hold, not just that they compile |
| `fixtures/seed_data.py` | Hand-authored adversarial dataset (+5:30 offset, Sunday–Thursday work week, a DST-transition meeting, back-to-back room bookings) — run with `python -m fixtures.seed_data` |
| `GUARDRAILS.md` | Self-audit checklist — the AI shortcuts interviewers specifically watch for |
| `web/` | React + TypeScript frontend (Vite): Find a time, Schedule a meeting, All meetings, Employee schedule, Dashboard. Dev server proxies `/health` and `/api/*` to uvicorn on `:8000`, so there's no CORS setup to do |

## Quick start

Backend:

```
cd build-demo-round
python -m venv .venv
.venv\Scripts\activate      # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

Frontend (separate terminal):

```
cd build-demo-round/web
npm install
npm run dev                 # http://localhost:5173, proxies API calls to :8000
```

`web/` targets Node 16+ (pinned to Vite 4 rather than 5 for that reason — if your
machine has Node 18+, feel free to bump to the latest Vite/plugin-react).

## How to use this for the real thing

1. Rename/copy this folder for the actual idea (don't build inside `build-demo-round/` itself).
2. Write your own migrations for your actual schema. Keep the `schema_migrations`
   runner as-is.
3. Build module by module: one migration + one repository function + one test +
   one endpoint, then move to the next feature. Don't generate the whole app in
   one prompt.
4. Before the demo, re-read `GUARDRAILS.md` against your actual code, and keep
   `fixtures/` adversarial — real edge cases, not happy-path rows.
5. `web/src/App.tsx` is a placeholder health check — replace it with real screens
   as endpoints land, and add each new route prefix to `web/vite.config.ts`'s
   proxy table.

## How meeting cost is calculated

"Find a time" (`app/scheduling/slots.py`) doesn't filter down to "everyone's
free" — it ranks candidate slots by an inconvenience *cost* per attendee,
then picks the one that minimizes the total without dumping all the pain on
one person.

**Hard constraints, checked before any cost is computed.** An existing
meeting conflict or a blackout date makes a slot infeasible for a
*required* attendee — the slot is dropped, not scored. An *optional*
attendee's conflict or blackout never blocks the slot, only excludes them
from that slot's cost.

**Soft cost, for everyone the slot survives hard-filtering for**, three
components summed per attendee (roughly "minutes of inconvenience"):

1. **Distance outside working hours** — 0 if the slot is fully inside that
   person's normal hours for that weekday; otherwise 1 point per minute
   outside, capped at 300. A day they have no working-hours row for at all
   (a day off) is a flat 240. A slot straddling a local midnight also maxes
   out at 300. This is deliberately *soft*, not a hard filter — a hard
   filter on working hours would make most cross-timezone meetings
   infeasible outright, which defeats the point of a fairness ranking.
2. **Calendar fragmentation** — a flat 15-point penalty for every existing
   meeting the slot leaves an "orphan gap" next to (0 < gap < 30 minutes) —
   a sliver of free time too short to be useful. Sitting flush against an
   existing meeting (0-minute gap, back-to-back) costs nothing.
3. **Daily load** — 0.15 points per minute this person already has booked
   that local day, capped at 120 — a nudge against stacking more onto an
   already-packed day.

**Usefulness weight.** The three sum, then multiply by a weight derived
from the meeting's `series_key` (an opaque tag for "meetings like this
one," e.g. a recurring 1:1). If this person has rated past meetings in
that series, their average usefulness score (1–5) maps to roughly
`avg / 3`: someone who's found the series valuable gets their convenience
protected more; someone who's rated it low gets deprioritized, since the
group's fairness budget is better spent on people who actually get value
from attending. No history (or no `series_key`) is neutral, `1.0×`.

**Ranking.** Candidates are sorted by `(total_cost, max_cost)` — the
`max_cost` tiebreak is the fairness mechanism: between two slots with equal
total pain, the one that doesn't concentrate it on one person wins.

## Path to production (documented, not built)

SQLite is fine for the demo. The one-line pitch for what changes later: swap
`app/db.py`'s connection factory for a pooled Postgres connection (e.g.
`psycopg` + a connection pool), keep the same repository-function shape, and
run the same `migrations/*.sql` files through a real migration tool (Alembic)
instead of the hand-rolled runner. Say this out loud in the demo — you don't
need to build it.
