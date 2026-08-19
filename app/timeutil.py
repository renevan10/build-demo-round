"""Timezone-safe time helpers.

The rule: store UTC everywhere, never read the server's local clock or local
timezone for anything user-facing, and take the user's IANA timezone name as
an explicit argument at every boundary that needs to reason about "today" or
"this month" from the user's point of view.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    """The only place allowed to call datetime.now() in this codebase."""
    return datetime.now(timezone.utc)


def to_user_local(instant_utc: datetime, user_tz: str) -> datetime:
    """Convert a UTC instant to the user's local wall-clock time.

    Raises if instant_utc is naive — every stored timestamp must be
    tz-aware UTC, so an accidental naive datetime fails loudly here instead
    of silently being treated as UTC or local.
    """
    if instant_utc.tzinfo is None:
        raise ValueError("instant_utc must be tz-aware (store UTC, always)")
    return instant_utc.astimezone(ZoneInfo(user_tz))


def user_local_date_str(instant_utc: datetime, user_tz: str) -> str:
    """The user's calendar date (YYYY-MM-DD) for a UTC instant.

    This is the function you call before doing any "is it the last day of
    the month for this user" logic — never derive that from UTC directly,
    or users near a UTC day boundary get billed on the wrong local date.
    """
    return to_user_local(instant_utc, user_tz).date().isoformat()
