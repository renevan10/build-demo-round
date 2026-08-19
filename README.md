# Build & Demo round — reusable scaffold

Not a project. This is the idea-agnostic skeleton you drop a chosen idea into
once the planning session picks one, so the first 20 minutes of the real
2-hour window aren't spent wiring up SQLite and a test runner.

## What's here

| Path | What it is |
|---|---|
| `app/db.py` | SQLite connection (WAL, foreign keys on) + a tiny migration runner |
| `app/timeutil.py` | Timezone-safe time helpers — explicit tz in, never the server clock |
| `app/repository_example.py` | Two patterns worth copying: DB-level unique constraint instead of check-then-insert, and a filtered/paginated SQL query instead of loading every row into memory |
| `app/main.py` | Minimal FastAPI app with a health check, wired to the DB |
| `migrations/0001_init.sql` | Example migration: `schema_migrations` tracking table + one demo table |
| `tests/` | Pytest harness with fixtures; `test_guardrails.py` proves the three patterns above actually hold, not just that they compile |
| `fixtures/README.md` | Where to hand-author the adversarial dataset once you know the domain |
| `GUARDRAILS.md` | Self-audit checklist — the AI shortcuts interviewers specifically watch for |

## Quick start

```
cd build-demo-round
python -m venv .venv
.venv\Scripts\activate      # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

## How to use this for the real thing

1. Rename/copy this folder for the actual idea (don't build inside `build-demo-round/` itself).
2. Delete `app/repository_example.py` and the demo table in `0001_init.sql` — they're
   references, not real domain code. Keep the *patterns*.
3. Write your own migrations for your actual schema. Keep the `schema_migrations`
   runner as-is.
4. Build module by module: one migration + one repository function + one test +
   one endpoint, then move to the next feature. Don't generate the whole app in
   one prompt.
5. Before the demo, re-read `GUARDRAILS.md` against your actual code, and fill in
   `fixtures/` with edge cases from your specific domain.

## Path to production (documented, not built)

SQLite is fine for the demo. The one-line pitch for what changes later: swap
`app/db.py`'s connection factory for a pooled Postgres connection (e.g.
`psycopg` + a connection pool), keep the same repository-function shape, and
run the same `migrations/*.sql` files through a real migration tool (Alembic)
instead of the hand-rolled runner. Say this out loud in the demo — you don't
need to build it.
