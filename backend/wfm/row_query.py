# -*- coding: utf-8 -*-
"""Server-side filtering for the demand table, so the browser stops holding the whole thing.

WHAT THIS REPLACES -- MEASURED
------------------------------
`GET /api/data` runs `SELECT * FROM <table>` with no WHERE clause:

    114,436 rows · 7.3 s · ~82.6 MB of JSON, on every page load

and the browser then filters that in JavaScript. 11,752 of those rows are pre-allocated future
weeks with no actual and no forecast -- shipped, parsed, and discarded. Measured alternatives:

    everything (today)                            114,436
    rows with a usable forecast + actual           71,780
    flagged at band 10%                            44,883
    flagged at band 10%, current fiscal year        6,264   <- the default view

So the week window does most of the work; `flagged_only` alone still returns 39% of the table.
Both are offered, and the default applies both.

WHY A WHITELIST AND NOT STRING INTERPOLATION
--------------------------------------------
Filter names arrive from a query string. Every VALUE is parameterised, and every COLUMN name is
checked against `FILTERABLE` before it reaches the SQL text. A column not on that list is
rejected outright rather than ignored -- silently dropping an unknown filter would return more
rows than the caller asked for, which on this endpoint means leaking rows the caller intended to
exclude.

THE TABLE IS A HEAP
-------------------
No primary key and no index of any kind (verified against the live server). Ordering and paging
therefore cost a scan. That is survivable at 114k rows and is the reason the migration in
`backend/migrations/` adds an index on (Forecast_name, Fiscal_Week) -- but nothing here depends
on that index existing, so this works before the migration is applied.
"""
from __future__ import annotations

# Columns a caller may filter on. Values are parameterised; these names are the only strings
# ever interpolated into the SQL text.
FILTERABLE = ("Region", "SubRegion", "Country", "Offering", "channel", "business_org",
              "Forecast_name", "Forecaster", "Volume_Category")

# Signed forecast adherence, computed in SQL so the filter can be applied before rows travel.
# NULLIF guards division by zero: a zero forecast yields NULL, which fails every comparison and
# so is excluded -- the same outcome the client-side code reaches, by the same reasoning.
ADHERENCE = "(1.0 - (Actual_Offered / NULLIF(fcst_offered, 0))) * 100.0"

# A row can only be judged when both sides exist and the forecast is non-zero. Anything else is
# not "adherence 0", it is "no adherence", and it must not reach a worklist.
USABLE = "Actual_Offered IS NOT NULL AND fcst_offered IS NOT NULL AND fcst_offered <> 0"

MAX_LIMIT = 20000


class FilterError(ValueError):
    """A caller asked for something we will not do. Surfaced as 400, never as fewer rows."""


def build_where(filters=None, week_from=None, week_to=None, flagged_only=False, band=10.0,
                usable_only=True):
    """Return (where_sql, params). `where_sql` never contains a caller-supplied value."""
    clauses, params = [], []

    if usable_only or flagged_only:
        clauses.append(USABLE)

    for name, value in (filters or {}).items():
        if value in (None, "", []):
            continue
        if name not in FILTERABLE:
            raise FilterError(f"'{name}' is not a filterable column. "
                              f"Allowed: {', '.join(FILTERABLE)}")
        values = value if isinstance(value, (list, tuple)) else [value]
        values = [v for v in values if v not in (None, "")]
        if not values:
            continue
        marks = ", ".join("?" for _ in values)
        clauses.append(f"[{name}] IN ({marks})")
        params.extend(values)

    for bound, op in ((week_from, ">="), (week_to, "<=")):
        if bound not in (None, ""):
            try:
                params.append(int(bound))
            except (TypeError, ValueError):
                raise FilterError(f"fiscal week bound must be a number, got {bound!r}")
            clauses.append(f"Fiscal_Week {op} ?")

    if flagged_only:
        try:
            b = abs(float(band))
        except (TypeError, ValueError):
            raise FilterError(f"band must be a number, got {band!r}")
        clauses.append(f"ABS({ADHERENCE}) > ?")
        params.append(b)

    return (" AND ".join(clauses) if clauses else "1=1"), params


def count_sql(table, where_sql):
    return f"SELECT COUNT(*) FROM {table} WHERE {where_sql}"


def rows_sql(table, where_sql, limit=5000, offset=0, order_desc=True):
    """Ordered, paged row query.

    ORDER BY is fixed rather than caller-supplied: it feeds OFFSET/FETCH, which requires a
    deterministic order, and a caller-chosen ordering column would be a second place to have to
    defend against injection for no benefit the UI asks for.
    """
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise FilterError("limit and offset must be numbers")
    if limit < 1:
        raise FilterError("limit must be at least 1")
    if limit > MAX_LIMIT:
        raise FilterError(f"limit exceeds the {MAX_LIMIT:,} row cap; page with offset instead")
    if offset < 0:
        raise FilterError("offset cannot be negative")
    direction = "DESC" if order_desc else "ASC"
    return (f"SELECT *, {ADHERENCE} AS Forecast_Adherence_Pct "
            f"FROM {table} WHERE {where_sql} "
            f"ORDER BY Fiscal_Week {direction}, Forecast_name ASC "
            f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY")


def facets_sql(table, column, where_sql):
    """Distinct values for one filter column, honouring the other filters already applied.

    The console needs these to populate its dropdowns without loading the table. The column is
    whitelist-checked by the caller before it gets here.
    """
    if column not in FILTERABLE:
        raise FilterError(f"'{column}' is not a filterable column")
    return (f"SELECT [{column}], COUNT(*) FROM {table} WHERE {where_sql} "
            f"GROUP BY [{column}] ORDER BY [{column}]")
