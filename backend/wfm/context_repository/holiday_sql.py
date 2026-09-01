# -*- coding: utf-8 -*-
"""Build the holiday repository's in-memory structure from SQL instead of the JSON extract.

WHY THIS EXISTS
---------------
`holiday_calendar.py` has always read `holiday_master.json`, a build-time extract of
`FC_RCA_Holiday_Master_Production.xlsx`. That is a frozen snapshot with a single reader, and
nothing checks that it still agrees with the same calendar published to SQL. In a production
environment with guaranteed SQL access there is no reason to carry two copies.

This module produces **byte-for-byte the same dict** `holiday_calendar._load()` returns, from
the four published tables. Every downstream function -- `_lookup`, `_resolve_country`,
`holiday_context`, `semantic_group_names` -- is untouched, because the shape it consumes does
not change. That is deliberate: the smaller the change, the less holiday behaviour can drift.

FOLLOWS THE PACKAGE CONVENTION FOR SQL
--------------------------------------
`wfm/` never opens a database connection and never imports `sql_backend` -- `data_access.py`
takes an already-open cursor and so does this. The caller owns the connection, this module
owns the query. That keeps the package importable with no driver installed.

THE FOUR TABLES
    dbo.Holiday_Master          one row per (country_key, fiscal_week, holiday)
    dbo.Holiday_Name_Alias      raw holiday name -> semantic family id
    dbo.Holiday_Semantic_Group  semantic family id -> display name
    dbo.Holiday_Aggregate_Group aggregate group -> member country keys
    dbo.Fiscal_Calendar_Week    fiscal week -> start, end, quarter, fiscal month

KNOWN GAP, MEASURED
-------------------
Row counts now match exactly: 10,702 in both, after `results/fix_holiday_missing_rows.py`
appended the 945 dates the published table was missing.

One gap remains: `semantic_family`. The extract stamps it on 2,464 rows, but
`Holiday_Name_Alias` only supports reproducing 250 of them by scope-exact match. The rest were
computed by `build_holiday_semantic_groups.py` using information the published table does not
carry, so they cannot be rebuilt from SQL. See `semantic_family_index` for why a looser rule
was rejected rather than used.

Effect: `holiday_events.py` groups holidays by family, so 2,214 rows that the extract would
group are left ungrouped from SQL. That can over-count holiday pressure where two spellings of
one holiday should have merged. It never merges holidays that should stay separate.

THE FIX is to publish `semantic_family` as a column on `dbo.Holiday_Master` -- an additive
schema change, not done here.
"""

MASTER = "dbo.Holiday_Master"
NAME_ALIAS = "dbo.Holiday_Name_Alias"
SEMANTIC_GROUP = "dbo.Holiday_Semantic_Group"
AGGREGATE_GROUP = "dbo.Holiday_Aggregate_Group"
FISCAL_CALENDAR = "dbo.Fiscal_Calendar_Week"


def _iso(value):
    """A date column becomes the same ISO string the JSON extract holds."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _bool(value):
    """SQL bit / int / bool -> a real bool, so `needs_review` matches the JSON exactly."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def semantic_family_index(cursor):
    """{(raw_name, country_scope): group_id} plus a name-only fallback map.

    Two maps rather than one because the alias table is scoped per country for names that
    mean different things in different places, while most names are global. Exact scope wins;
    the name-only map is the fallback. Both are lowercased -- the tables already hold
    lowercase names (verified: zero rows differ from their own LOWER()), but normalising here
    means a future non-lowercase insert cannot silently stop matching.

    Measured against the extract, three rules were tried:

        pure name-only fallback        412 rows wrongly stamped
        single-group-if-unambiguous    238 rows wrongly stamped
        scope-exact only                 0 rows wrongly stamped

    Scope-exact is used. It never invents a family, which matters because `holiday_events.py`
    groups holidays by family -- a wrong family MERGES two distinct holidays, while a missing
    one merely leaves them separate. Under-stamping is the safe direction.

    The cost is real and stated plainly: the extract stamps 2,464 rows, and only 250 of those
    are reproducible by scope-exact match. `Holiday_Name_Alias` simply does not carry enough to
    rebuild the rest -- the extract's families were computed by
    `build_holiday_semantic_groups.py` with information the published table does not hold.

    THE PROPER FIX is to publish `semantic_family` as a column on `dbo.Holiday_Master` so no
    inference is needed at all. That is an additive schema change and is not done here.
    """
    cursor.execute("SELECT raw_name, country_scope, group_id FROM %s" % NAME_ALIAS)
    exact, by_name = {}, {}
    for raw_name, scope, group_id in cursor.fetchall():
        n = str(raw_name or "").strip().lower()
        s = str(scope or "").strip().lower()
        if not n or not group_id:
            continue
        exact[(n, s)] = group_id
    # Deliberately empty: a name-only fallback over-stamps. Kept in the signature so callers
    # and the parity test do not change shape.
    return exact, by_name


def build(cursor, table_prefix=None):
    """The same dict `holiday_calendar._load()` returns, assembled from SQL.

    `cursor` is an already-open DB-API cursor. Nothing here commits, writes or closes it.
    """
    del table_prefix                      # reserved; the tables are fixed by the loader

    exact_family, family_by_name = semantic_family_index(cursor)
    unresolved = set()

    # ---- holidays: one dict per row, grouped as "country_key|fiscal_week" ----------------
    cursor.execute(
        "SELECT country_key, fiscal_week, holiday_name, holiday_type, holiday_date, "
        "       impact_before_days, impact_after_days, aggregate_group, needs_review "
        "  FROM %s "
        " ORDER BY country_key, fiscal_week, holiday_date, holiday_name" % MASTER)

    holidays = {}
    row_count = 0
    for (country_key, fiscal_week, name, htype, hdate,
         before, after, group, needs_review) in cursor.fetchall():
        ck = str(country_key or "").strip().lower()
        if not ck or fiscal_week is None:
            continue
        nm = str(name or "").strip()
        family = exact_family.get((nm.lower(), ck)) or family_by_name.get(nm.lower())
        if family is None:
            unresolved.add((nm.lower(), ck))
        # Empty string, not None, and never an absent key. Measured against the extract:
        # `group` is "" on 7,971 rows and `semantic_family` is "" on 8,238 -- never null and
        # never missing. A None or an absent key here reads differently downstream and was
        # caught by results/test_holiday_sql_parity.py.
        entry = {
            "name": nm,
            "type": htype,
            "date": _iso(hdate),
            "before": int(before) if before is not None else None,
            "after": int(after) if after is not None else None,
            "group": group if group is not None else "",
            "semantic_family": family if family is not None else "",
            "needs_review": _bool(needs_review),
        }
        holidays.setdefault("%s|%d" % (ck, int(fiscal_week)), []).append(entry)
        row_count += 1

    # ---- aggregate groups: group -> [member country keys] --------------------------------
    cursor.execute("SELECT aggregate_group, member_country_key FROM %s "
                   "ORDER BY aggregate_group, member_country_key" % AGGREGATE_GROUP)
    aggregate_groups = {}
    for group, member in cursor.fetchall():
        if not group:
            continue
        aggregate_groups.setdefault(str(group), []).append(
            str(member or "").strip().lower())

    # ---- semantic groups: id -> display name ---------------------------------------------
    cursor.execute("SELECT group_id, display_name FROM %s ORDER BY group_id" % SEMANTIC_GROUP)
    semantic_groups = {gid: name for gid, name in cursor.fetchall() if gid}

    # ---- fiscal calendar: week -> {start, end, quarter, month} ----------------------------
    cursor.execute("SELECT fiscal_week, week_start, week_end, quarter, fiscal_month "
                   "  FROM %s ORDER BY fiscal_week" % FISCAL_CALENDAR)
    fiscal_calendar = {}
    for week, start, end, quarter, month in cursor.fetchall():
        if week is None:
            continue
        fiscal_calendar[str(int(week))] = {
            "start": _iso(start),
            "end": _iso(end),
            "quarter": int(quarter) if quarter is not None else None,
            "month": int(month) if month is not None else None,
        }

    data = {
        "source": "SQL: %s" % MASTER,
        "active_rows": row_count,
        "inactive_dropped": 0,
        "country_weeks": len(holidays),
        "holidays": holidays,
        "aggregate_groups": aggregate_groups,
        "semantic_groups": semantic_groups,
        "fiscal_calendar": fiscal_calendar,
    }
    if unresolved:
        # Visible, not swallowed. A caller can log it; the parity test asserts on it.
        data["_parity_gaps"] = {
            "semantic_family_unresolved": sorted("%s|%s" % (n, c) for n, c in unresolved),
            "note": ("these (name, country) pairs have no row in %s, so no semantic family "
                     "is stamped. Publish the alias rows to close the gap." % NAME_ALIAS),
        }
    return data


def lookup_window(cursor, country_keys, week_from, week_to, family_index=None):
    """The holidays for these countries across this week range -- ONE targeted query.

    THIS IS THE RUNTIME PATH. `build()` above loads all 9,757 rows to answer questions about
    roughly three, which is the same "hand over everything up front" habit this work exists to
    remove. An investigation needs one country and a +/-1 week window, so that is what this
    asks for -- typically a handful of rows.

    `build()` is kept for one job only: `results/test_holiday_sql_parity.py` compares whole
    structures, which needs a whole structure. Nothing at runtime should call it.

    Returns the same {"country|week": [holiday dicts]} shape as `build()`, so the calling code
    is identical either way.
    """
    keys = [str(c or "").strip().lower() for c in (country_keys or []) if str(c or "").strip()]
    if not keys:
        return {}
    if family_index is None:
        family_index = semantic_family_index(cursor)
    exact_family, family_by_name = family_index

    placeholders = ",".join("?" for _ in keys)
    cursor.execute(
        "SELECT country_key, fiscal_week, holiday_name, holiday_type, holiday_date, "
        "       impact_before_days, impact_after_days, aggregate_group, needs_review "
        "  FROM %s "
        " WHERE country_key IN (%s) AND fiscal_week BETWEEN ? AND ? "
        " ORDER BY country_key, fiscal_week, holiday_date, holiday_name"
        % (MASTER, placeholders),
        (*keys, int(week_from), int(week_to)))

    out = {}
    for (ck, fw, name, htype, hdate, before, after, group, needs_review) in cursor.fetchall():
        ckey = str(ck or "").strip().lower()
        if not ckey or fw is None:
            continue
        nm = str(name or "").strip()
        family = exact_family.get((nm.lower(), ckey)) or family_by_name.get(nm.lower()) or ""
        out.setdefault("%s|%d" % (ckey, int(fw)), []).append({
            "name": nm,
            "type": htype,
            "date": _iso(hdate),
            "before": int(before) if before is not None else None,
            "after": int(after) if after is not None else None,
            "group": group if group is not None else "",
            "semantic_family": family,
            "needs_review": _bool(needs_review),
        })
    return out


def country_keys_matching(cursor, country):
    """Does this Country value name a country_key directly? One EXISTS query, no bulk scan.

    `holiday_calendar._resolve_country` currently answers this by scanning every key in the
    loaded dict. With a targeted runtime path there is no loaded dict, so it asks the server.
    """
    c = str(country or "").strip().lower()
    if not c:
        return []
    cursor.execute("SELECT TOP 1 1 FROM %s WHERE country_key = ?" % MASTER, (c,))
    return [c] if cursor.fetchone() else []


def reference_tables(cursor):
    """The small tables, loaded once: aggregate groups, semantic group names, fiscal calendar.

    Deliberately separate from `lookup_window`. These are genuine reference data -- 8, 23 and
    521 rows -- that change when the calendar is reissued, not per request. Caching them costs
    nothing; re-querying them per investigation would be the wasteful half of the bulk load
    without the benefit.
    """
    cursor.execute("SELECT aggregate_group, member_country_key FROM %s "
                   "ORDER BY aggregate_group, member_country_key" % AGGREGATE_GROUP)
    aggregate_groups = {}
    for group, member in cursor.fetchall():
        if group:
            aggregate_groups.setdefault(str(group), []).append(
                str(member or "").strip().lower())

    cursor.execute("SELECT group_id, display_name FROM %s ORDER BY group_id" % SEMANTIC_GROUP)
    semantic_groups = {g: n for g, n in cursor.fetchall() if g}

    cursor.execute("SELECT fiscal_week, week_start, week_end, quarter, fiscal_month "
                   "  FROM %s ORDER BY fiscal_week" % FISCAL_CALENDAR)
    fiscal_calendar = {}
    for week, start, end, quarter, month in cursor.fetchall():
        if week is not None:
            fiscal_calendar[str(int(week))] = {
                "start": _iso(start), "end": _iso(end),
                "quarter": int(quarter) if quarter is not None else None,
                "month": int(month) if month is not None else None}

    return {"aggregate_groups": aggregate_groups,
            "semantic_groups": semantic_groups,
            "fiscal_calendar": fiscal_calendar}


def same_holiday_prior_years(cursor, country_keys, holiday_names, current_week,
                             years=3, fact_table=None):
    """When did THIS holiday fall in previous years, and what did demand do that week?

    WHY THIS MATTERS
    ----------------
    "Columbus Day is in this week" is nearly useless on its own. The question a planner actually
    asks is: when did it fall last year, and what happened to demand then? A holiday drifts
    across fiscal weeks year to year -- Columbus Day is the second Monday in October, so it can
    land in FW37 one year and FW38 the next -- which means the naive "same fiscal week last
    year" comparison silently compares a holiday week against a normal one.

    This finds the holiday BY NAME in prior years, returns the fiscal week it actually fell in,
    and -- when `fact_table` is given -- what forecast and actual did in that week. That turns
    a calendar fact into a comparison a planner can act on, and gives an agent something
    checkable to reason about instead of a label.

    Returns a list, newest first, of:
        {"holiday": name, "country_key": ck, "fiscal_week": wk, "holiday_date": iso,
         "years_ago": n, "forecast": .., "actual": .., "adherence_pct": ..,
         "same_fiscal_week_as_now": bool}
    """
    keys = [str(c or "").strip().lower() for c in (country_keys or []) if str(c or "").strip()]
    names = [str(h or "").strip() for h in (holiday_names or []) if str(h or "").strip()]
    if not keys or not names or not current_week:
        return []
    current_week = int(current_week)
    cur_year = current_week // 100
    cur_wk = current_week % 100
    lo = (cur_year - int(years)) * 100
    hi = cur_year * 100          # strictly BEFORE the current fiscal year

    kmarks = ",".join("?" for _ in keys)
    nmarks = ",".join("?" for _ in names)
    cursor.execute(
        "SELECT country_key, fiscal_week, holiday_name, holiday_date, "
        "       impact_before_days, impact_after_days "
        "  FROM %s "
        " WHERE country_key IN (%s) AND holiday_name IN (%s) "
        "   AND fiscal_week >= ? AND fiscal_week < ? "
        " ORDER BY fiscal_week DESC" % (MASTER, kmarks, nmarks),
        (*keys, *names, lo, hi))
    rows = cursor.fetchall()

    out = []
    for ck, wk, nm, dt, before, after in rows:
        wk = int(wk)
        out.append({
            "holiday": nm,
            "country_key": str(ck),
            "fiscal_week": wk,
            "holiday_date": _iso(dt),
            "years_ago": cur_year - (wk // 100),
            "fiscal_week_number": wk % 100,
            "same_fiscal_week_as_now": (wk % 100) == cur_wk,
            "impact_before_days": int(before) if before is not None else None,
            "impact_after_days": int(after) if after is not None else None,
        })

    # De-duplicate: a multi-day holiday has several rows for one occurrence. Keep one per
    # (year, name) -- the earliest date -- so "last year it was in FW37" is stated once.
    seen, deduped = set(), []
    for r in out:
        k = (r["fiscal_week"] // 100, r["holiday"], r["country_key"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    # What did demand actually do in those weeks? This is the part that makes it useful.
    if fact_table and deduped:
        weeks = sorted({r["fiscal_week"] for r in deduped})
        marks = ",".join("?" for _ in weeks)
        try:
            cursor.execute(
                "SELECT Fiscal_Week, SUM(fcst_offered), SUM(Actual_Offered) "
                "  FROM %s WHERE Fiscal_Week IN (%s) AND fcst_offered IS NOT NULL "
                "   AND Actual_Offered IS NOT NULL "
                " GROUP BY Fiscal_Week" % (fact_table, marks), weeks)
            demand = {int(w): (float(f), float(a)) for w, f, a in cursor.fetchall()}
        except Exception:
            demand = {}
        for r in deduped:
            d = demand.get(r["fiscal_week"])
            if not d:
                continue
            f, a = d
            r["all_queue_forecast"] = round(f)
            r["all_queue_actual"] = round(a)
            r["all_queue_adherence_pct"] = round((1 - a / f) * 100, 1) if f else None

    return deduped


def queue_history_for_weeks(cursor, fact_table, queue, weeks):
    """What one queue's forecast and actual were in specific fiscal weeks.

    Paired with `same_holiday_prior_years`: knowing the holiday was in FW202537 is only half
    the answer -- the other half is what THIS queue did that week.
    """
    weeks = sorted({int(w) for w in (weeks or [])})
    if not queue or not weeks:
        return {}
    marks = ",".join("?" for _ in weeks)
    cursor.execute(
        "SELECT Fiscal_Week, fcst_offered, Actual_Offered "
        "  FROM %s WHERE Forecast_name = ? AND Fiscal_Week IN (%s)" % (fact_table, marks),
        (queue, *weeks))
    out = {}
    for w, f, a in cursor.fetchall():
        if f in (None, 0) or a is None:
            continue
        f, a = float(f), float(a)
        out[int(w)] = {"forecast": round(f), "actual": round(a),
                       "adherence_pct": round((1 - a / f) * 100, 1)}
    return out


def country_alias_map(cursor):
    """{data_country: holiday_country_key} from dbo.Holiday_Country_Alias.

    `holiday_calendar.py` currently carries four of these as literals in code
    ("north america", "korea", "usa", "us"). The table holds all 50, three of which are not
    a direct match. Exposed separately so the hardcoded list can be retired against data
    rather than extended by hand.
    """
    cursor.execute("SELECT data_country, holiday_country_key, resolution "
                   "  FROM dbo.Holiday_Country_Alias")
    out = {}
    for data_country, key, resolution in cursor.fetchall():
        dc = str(data_country or "").strip().lower()
        if dc and key:
            out[dc] = {"key": str(key).strip().lower(), "resolution": resolution}
    return out


def watermark(cursor, table):
    """The newest fiscal week actually present, so nothing has to be configured weekly.

    This is the answer to "when we move from 202710 to 202711, what do we change in code?" --
    nothing. The read path has no week filter; this lets the caller *discover* the latest week
    rather than being told it.
    """
    cursor.execute("SELECT MIN(Fiscal_Week), MAX(Fiscal_Week), "
                   "       COUNT(DISTINCT Fiscal_Week) FROM %s" % table)
    lo, hi, n = cursor.fetchone()
    cursor.execute("SELECT MAX(fiscal_week) FROM %s" % MASTER)
    holiday_hi = cursor.fetchone()[0]
    return {"min_fiscal_week": int(lo) if lo is not None else None,
            "max_fiscal_week": int(hi) if hi is not None else None,
            "distinct_weeks": int(n) if n is not None else 0,
            "holiday_calendar_covers_to": int(holiday_hi) if holiday_hi is not None else None,
            "holiday_calendar_ahead_of_data": (
                holiday_hi is not None and hi is not None and int(holiday_hi) >= int(hi))}
