"""Batch lookups that feed app/scheduling/slots.py's pure EmployeeContext.

One query per data source for the whole set of candidate employees, not
one query per employee per candidate slot -- the slot-suggester evaluates
many candidate slots against the same small set of people, so doing this
per-slot would be an N+1 trap at exactly the point where it matters most.
"""

from __future__ import annotations

import sqlite3

from app.scheduling.slots import EmployeeContext


def get_working_hours(conn: sqlite3.Connection, employee_ids: list[int]) -> dict[int, dict[int, tuple[str, str]]]:
    if not employee_ids:
        return {}
    placeholders = ",".join("?" * len(employee_ids))
    rows = conn.execute(
        f"SELECT employee_id, day_of_week, start_local, end_local "
        f"FROM working_hours WHERE employee_id IN ({placeholders})",
        employee_ids,
    ).fetchall()
    result: dict[int, dict[int, tuple[str, str]]] = {eid: {} for eid in employee_ids}
    for row in rows:
        result[row["employee_id"]][row["day_of_week"]] = (row["start_local"], row["end_local"])
    return result


def get_blackouts(conn: sqlite3.Connection, employee_ids: list[int]) -> dict[int, frozenset[str]]:
    if not employee_ids:
        return {}
    placeholders = ",".join("?" * len(employee_ids))
    rows = conn.execute(
        f"SELECT employee_id, local_date FROM blackouts WHERE employee_id IN ({placeholders})",
        employee_ids,
    ).fetchall()
    result: dict[int, set[str]] = {eid: set() for eid in employee_ids}
    for row in rows:
        result[row["employee_id"]].add(row["local_date"])
    return {eid: frozenset(dates) for eid, dates in result.items()}


def get_busy_intervals(
    conn: sqlite3.Connection, employee_ids: list[int], search_start_utc: str, search_end_utc: str
) -> dict[int, list[tuple[str, str]]]:
    """Every non-cancelled meeting each employee has that overlaps the
    search window -- covers both hard-conflict checks and the soft
    fragmentation/daily-load costs, which need to see meetings adjacent to
    the window too (hence comparing against the window boundaries directly
    rather than padding: any meeting that overlaps at all is relevant)."""
    if not employee_ids:
        return {}
    placeholders = ",".join("?" * len(employee_ids))
    rows = conn.execute(
        f"SELECT mp.employee_id, m.start_utc, m.end_utc "
        f"FROM meetings m JOIN meeting_participants mp ON mp.meeting_id = m.id "
        f"WHERE mp.employee_id IN ({placeholders}) AND m.status != 'cancelled' "
        f"AND m.start_utc < ? AND m.end_utc > ? "
        f"ORDER BY m.start_utc",
        (*employee_ids, search_end_utc, search_start_utc),
    ).fetchall()
    result: dict[int, list[tuple[str, str]]] = {eid: [] for eid in employee_ids}
    for row in rows:
        result[row["employee_id"]].append((row["start_utc"], row["end_utc"]))
    return result


def get_usefulness_weights(
    conn: sqlite3.Connection, series_key: str | None, employee_ids: list[int]
) -> dict[int, float]:
    """Average past usefulness_score (1-5) for this series, mapped to a
    cost multiplier: 3 (neutral midpoint) -> 1.0x, 5 -> ~1.67x (protect
    their convenience more -- they get real value from this), 1 -> ~0.33x
    (spend the group's fairness budget elsewhere; this isn't worth much to
    them). No history, or no series_key at all, is neutral (1.0x)."""
    weights = {eid: 1.0 for eid in employee_ids}
    if series_key is None or not employee_ids:
        return weights

    rows = conn.execute(
        "SELECT mf.employee_id, AVG(mf.usefulness_score) AS avg_score "
        "FROM meeting_feedback mf "
        "JOIN meetings m ON m.id = mf.meeting_id "
        "WHERE m.series_key = ? "
        "GROUP BY mf.employee_id",
        (series_key,),
    ).fetchall()
    for row in rows:
        if row["employee_id"] in weights:
            weights[row["employee_id"]] = row["avg_score"] / 3.0
    return weights


def build_employee_contexts(
    conn: sqlite3.Connection,
    employee_ids: list[int],
    timezones_by_id: dict[int, str],
    search_start_utc: str,
    search_end_utc: str,
    series_key: str | None,
) -> dict[int, EmployeeContext]:
    working_hours = get_working_hours(conn, employee_ids)
    blackouts = get_blackouts(conn, employee_ids)
    busy = get_busy_intervals(conn, employee_ids, search_start_utc, search_end_utc)
    weights = get_usefulness_weights(conn, series_key, employee_ids)

    return {
        eid: EmployeeContext(
            employee_id=eid,
            timezone=timezones_by_id[eid],
            working_hours=working_hours.get(eid, {}),
            blackout_local_dates=blackouts.get(eid, frozenset()),
            busy_intervals_utc=tuple(busy.get(eid, [])),
            usefulness_weight=weights.get(eid, 1.0),
        )
        for eid in employee_ids
    }
