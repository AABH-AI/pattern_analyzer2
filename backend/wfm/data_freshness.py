# -*- coding: utf-8 -*-
"""Is the demand data we are looking at still the data that is in SQL?

WHY THIS EXISTS
---------------
The source table is reloaded on a fixed cadence (weekly in the target environment). A console
left open across that boundary keeps showing the previous load's picture, and nothing in the
product says so. Worse, `_SUMMARY_CACHE` is keyed on queue + week + prompt version, so after a
restatement it will happily serve a summary computed from figures that no longer exist.

This module produces a short TOKEN that changes when the data changes. Clients hold the token
they were served; when the token moves, their view is stale and they are told.

TWO WAYS TO KNOW, AND WHY BOTH ARE HERE
---------------------------------------
1. `load_column` (preferred) -- a LoadedAt/batch column written by the ingestion job. Exact,
   cheap, and it distinguishes "reloaded with identical values" from "not reloaded".
2. derived (fallback) -- max fiscal week with actuals, row count, and CHECKSUM_AGG over the
   two measure columns. Detects an appended week AND a restatement of an old one, because the
   checksum covers every row, not just the frontier.

The fallback exists because the column does not exist in every environment yet, and an
environment without it must still detect refreshes rather than silently going stale. Which one
was used is reported in `source`, so a reader can tell an exact answer from an inferred one.

NO ASSUMPTION ABOUT THE CADENCE
-------------------------------
Nothing here knows that the load happens on a Monday. A cadence stated in config is used only
to WORD the message ("expected weekly"); staleness is decided by the token changing, never by
the clock. An environment that reloads twice a week, or late, or not at all, is handled by the
same code -- an assumed schedule would report a refresh that never happened.
"""
from __future__ import annotations

import hashlib

# Columns whose values define "the data changed". Deliberately the two the whole product is
# built on: if neither moved, no RCA anywhere would reach a different conclusion.
_MEASURE_COLS = ("Actual_Offered", "fcst_offered")


def _token(parts):
    """A short stable digest. Short because it travels on every response and is compared, not
    read; stable because clients persist it across page loads."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def probe(cur, table, load_column=None):
    """Cheap freshness probe. Aggregates only -- it never returns rows.

    Returns a dict that is always safe to serialise, even on failure: callers put this on user
    responses and a raising probe must not take an investigation down with it.
    """
    out = {"available": False, "source": None, "token": None, "error": None}
    try:
        cur.execute(
            "SELECT COUNT(*), "
            "  SUM(CASE WHEN Actual_Offered IS NOT NULL THEN 1 ELSE 0 END), "
            "  MAX(CASE WHEN Actual_Offered IS NOT NULL THEN Fiscal_Week END), "
            "  MAX(Fiscal_Week) "
            f"FROM {table}")
        row = cur.fetchone() or (None, None, None, None)
        out["row_count"] = int(row[0] or 0)
        out["rows_with_actuals"] = int(row[1] or 0)
        out["frontier_week"] = row[2]
        out["max_week"] = row[3]
    except Exception as exc:                                  # pragma: no cover - driver/permission
        out["error"] = f"frontier probe failed: {exc}"
        return out

    stamp = None
    if load_column:
        try:
            cur.execute(f"SELECT MAX([{load_column}]) FROM {table}")
            stamp = (cur.fetchone() or [None])[0]
            out["loaded_at"] = str(stamp) if stamp is not None else None
            out["source"] = "load_column"
        except Exception as exc:
            # The column is configured but absent or unreadable. Fall through to derived rather
            # than failing: a misconfigured column name must degrade to a working probe, not to
            # no probe at all. The reason is reported so it can be fixed.
            out["load_column_error"] = f"{load_column}: {exc}"

    if out["source"] != "load_column":
        try:
            # One CHECKSUM_AGG per column, combined in Python -- NOT summed in SQL. Each returns
            # an `int`, and adding two of them overflows: SQL Server raises 22003 "Arithmetic
            # overflow error converting expression to data type int" rather than wrapping. Found
            # by the sensitivity test, which is why that test exercises real values.
            cols = ", ".join(f"CHECKSUM_AGG(CHECKSUM([{c}]))" for c in _MEASURE_COLS)
            cur.execute(f"SELECT {cols} FROM {table}")
            vals = list(cur.fetchone() or [])
            out["measure_checksums"] = [None if v is None else int(v) for v in vals]
            stamp = ":".join("" if v is None else str(int(v)) for v in vals)
            out["source"] = "derived"
        except Exception as exc:
            out["error"] = f"checksum probe failed: {exc}"
            return out

    out["token"] = _token([out.get("row_count"), out.get("rows_with_actuals"),
                           out.get("frontier_week"), stamp])
    out["available"] = True
    return out


def compare(client_token, current):
    """What to tell a client holding `client_token`.

    `stale` is only ever True when we KNOW the token moved. An unavailable probe reports
    unknown, never stale -- warning about a refresh that may not have happened trains people to
    dismiss the warning.
    """
    cur_token = (current or {}).get("token")
    if not (current or {}).get("available") or not cur_token:
        return {"stale": False, "known": False,
                "reason": (current or {}).get("error") or "freshness could not be determined"}
    if not client_token:
        return {"stale": False, "known": True, "reason": "no client token supplied"}
    if client_token == cur_token:
        return {"stale": False, "known": True, "reason": "client is on the current load"}
    return {"stale": True, "known": True,
            "reason": "the source data has been reloaded since this view was built",
            "client_token": client_token, "current_token": cur_token}


def describe(current, cadence=None):
    """One sentence for a human. Cadence, when configured, is context -- not evidence."""
    c = current or {}
    if not c.get("available"):
        return c.get("error") or "data freshness is unknown."
    bits = [f"{c.get('row_count', 0):,} rows",
            f"actuals to fiscal week {c.get('frontier_week')}"]
    if c.get("loaded_at"):
        bits.append(f"loaded {c['loaded_at']}")
    line = "Source data: " + ", ".join(bits) + "."
    if cadence:
        line += f" Expected refresh cadence: {cadence}."
    if c.get("source") == "derived":
        line += " (No load-timestamp column in this environment; change is detected by checksum.)"
    return line
