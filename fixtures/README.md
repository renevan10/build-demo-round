# Adversarial dataset — fill in once you pick an idea

Don't seed this with clean happy-path rows. The brief specifically calls out
hand-authoring data designed to break default logic. Domain-agnostic edge
case categories to translate into your actual domain:

- **Boundary dates**: something that happens on the 31st in a 30-day (or
  28/29-day) month; a leap day; a period that starts and ends on the same
  calendar day; midnight in a non-UTC timezone straddling a day boundary.
- **Reversals that must not corrupt history**: a refund/cancellation/edit
  arriving *after* downstream state already depended on the original — prove
  your logic appends a compensating record rather than mutating the past.
- **Sparse data**: an entity with zero related rows, exactly one, and the
  page-size boundary (e.g. exactly `limit` rows, `limit + 1` rows).
- **Out-of-order or duplicate arrivals**: the same logical event delivered
  twice (idempotency), or events arriving out of chronological order.
- **Extremes**: an empty string vs null vs missing field; a value at exactly
  a threshold (>=, not >) both sides of any comparison in your business logic.

Write these as fixtures + tests, not just seed data you eyeball in a demo —
the point is a test that fails if the edge case is handled wrong.
