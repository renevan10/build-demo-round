"""Proves the three patterns in GUARDRAILS.md actually hold.

These are the tests worth keeping around as a template: each one exists to
disprove a specific lazy-AI shortcut, not just to exercise happy-path code.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.repository_example import DuplicateEventError, create_idempotent, list_paginated
from app.timeutil import to_user_local, user_local_date_str


def test_duplicate_idempotency_key_is_rejected_not_double_inserted(conn):
    create_idempotent(conn, "key-1", "first payload", "2026-01-01T00:00:00Z")

    with pytest.raises(DuplicateEventError):
        create_idempotent(conn, "key-1", "second payload", "2026-01-01T00:00:05Z")

    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM demo_events WHERE idempotency_key = ?", ("key-1",)
    ).fetchone()
    assert rows["n"] == 1, "check-then-insert would let a race produce 2 rows here"


def test_pagination_returns_correct_slice_without_full_scan(conn):
    for i in range(25):
        create_idempotent(conn, f"key-{i}", f"payload-{i}", "2026-01-01T00:00:00Z")

    page = list_paginated(conn, limit=10, offset=20)

    assert [e.idempotency_key for e in page] == [f"key-{i}" for i in range(20, 25)]
    assert len(page) == 5


def test_pagination_past_the_end_is_empty_not_an_error(conn):
    create_idempotent(conn, "only-key", "payload", "2026-01-01T00:00:00Z")

    page = list_paginated(conn, limit=10, offset=1000)

    assert page == []


def test_naive_datetime_is_rejected_not_silently_treated_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)

    with pytest.raises(ValueError):
        to_user_local(naive, "America/New_York")


def test_user_local_date_can_differ_from_utc_date_near_midnight():
    # 2026-01-01 03:00 UTC is still 2025-12-31 22:00 in New York (UTC-5, no DST in January).
    instant = datetime(2026, 1, 1, 3, 0, 0, tzinfo=timezone.utc)

    utc_date = instant.date().isoformat()
    user_date = user_local_date_str(instant, "America/New_York")

    assert utc_date == "2026-01-01"
    assert user_date == "2025-12-31"
    assert utc_date != user_date, "billing 'today' off the server/UTC date would charge the wrong day"


def test_end_of_month_local_date_across_a_dst_transition():
    # US spring-forward 2026: clocks jump 2:00am -> 3:00am on 2026-03-08 in America/New_York.
    # 06:30 UTC on 2026-03-08 is 01:30 local (pre-jump, UTC-5) the *same* morning.
    before_jump = datetime(2026, 3, 8, 6, 30, 0, tzinfo=timezone.utc)
    after_jump = datetime(2026, 3, 8, 7, 30, 0, tzinfo=timezone.utc)

    assert user_local_date_str(before_jump, "America/New_York") == "2026-03-08"
    assert user_local_date_str(after_jump, "America/New_York") == "2026-03-08"
    assert to_user_local(before_jump, "America/New_York").hour == 1
    assert to_user_local(after_jump, "America/New_York").hour == 3
