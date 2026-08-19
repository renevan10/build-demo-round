# Self-audit checklist

Read this against your own code before the demo — specifically because you
used AI tooling to write most of it. These are the shortcuts AI defaults to
and that interviewers are told to look for.

- [ ] **Uniqueness is enforced at the DB level**, not with a check-then-insert
      (`SELECT ... ; if not exists: INSERT`). That pattern race-conditions
      under concurrent requests. Use a `UNIQUE` constraint/index and catch the
      integrity error. See `app/repository_meetings.py::create_meeting_idempotent`.
- [ ] **No code path reads the server's local clock or local timezone** for
      anything user-facing. Store UTC, take the user's timezone as an explicit
      parameter, convert at the edge. See `app/timeutil.py`.
- [ ] **No query pulls a full table into memory to filter/paginate in Python.**
      Filter, sort, and `LIMIT`/`OFFSET` in SQL. See
      `app/repository_meetings.py::list_employee_schedule`.
- [ ] **A resource only one party can use at a time (a meeting room) is
      protected against a genuine race, not a check-then-insert that only
      looks safe in a single-threaded demo.** See
      `app/repository_meetings.py::create_meeting_idempotent`'s `BEGIN IMMEDIATE`
      + overlap query, and why `app/db.py::connect` sets `isolation_level=None`.
- [ ] **Date-math edge cases are tested, not assumed** — end-of-month billing
      on the 31st into a 30-day (or 28/29-day) month, DST transitions if you
      touch local time anywhere, leap years if you touch Feb.
- [ ] **A refund/reversal doesn't silently corrupt history** — appending a
      compensating record beats mutating or deleting the original.
- [ ] **Sparse/empty results are a real code path**, not just the happy path —
      zero rows, one row, and the max page size all need a test.
- [ ] **You can name your isolation/locking story in one sentence** for any
      write that matters (e.g. "single UPDATE with a WHERE clause on version,
      so it's optimistic-locked" or "unique constraint does the serialization
      for me"). If the honest answer is "the DB just handles it," dig one
      level deeper before the demo.
- [ ] **You know your commit history tells a story** — small, verified steps
      with visible corrections beat one giant AI-generated diff. If you
      squashed away every revert, that's a tell in the wrong direction.

## Rough QPS/scale sanity check (only if the domain has a scale dimension)

Write down: expected requests/sec, rows in the relevant table after a year of
that load, and whether an index actually covers your hot query's `WHERE`/`ORDER
BY`. If you didn't do this math, don't claim a scaling property in the demo.
