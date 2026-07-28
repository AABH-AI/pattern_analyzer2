"""SQL fetching for the WFM engine.

Takes an already-open cursor so this package never imports sql_backend (which would
be circular). The caller owns the connection.

PERFORMANCE NOTE -- do not reintroduce a correlated subquery here. The channel-sibling
query originally resolved the prior week with
    ... OR Fiscal_Week = (SELECT MAX(Fiscal_Week) ... WHERE <dims> AND Fiscal_Week < ?)
On this table -- which carries no index on these columns -- that measured 101.5s, while
every other query in this module runs in 0.02-0.05s. A single investigation appeared to
hang. The prior week is already known from the 104-week history, so it is passed as a
literal and the lookup is a plain IN (?, ?). Measured: 98.19s -> 0.16s.
"""
from .common import CHANNEL_SIBLING_DIMS, WFM_HISTORY_WEEKS, adherence_pct, prior_year_week

# Columns the correlation engine and the temporal reasoner need from history.
_HISTORY_COLS = ("Fiscal_Week", "Actual_Offered", "fcst_offered", "Holiday_Count",
                 "Projection_plan_name", "Planned_ASU", "Actual_ASU", "Final_Units")

# Levels for the investigation ladder, highest first. Each entry is the grouping that
# defines that level; a level is skipped if any of its dimensions is missing.
_LADDER_LEVELS = (
    ("Business Org", ["business_org"]),
    ("Region", ["business_org", "Region"]),
    ("SubRegion", ["business_org", "Region", "SubRegion"]),
    ("Country", ["business_org", "Region", "SubRegion", "Country"]),
    ("Channel", ["business_org", "Region", "SubRegion", "Country", "channel"]),
)


def fetch_wfm_context(cur, table, key):
    """Fetch the deeper context the WFM prompt needs.

    key = {"Forecast_name", "Fiscal_Week", "Region", "SubRegion", "Country",
           "channel", "business_org"}

    Returns raw blocks only -- every derived number is computed by the analyzer
    modules, never here.
    """
    name = key.get("Forecast_name")
    week = key.get("Fiscal_Week")
    out = {"history_104": [], "history_forward": [], "channel_sibling_rows": [],
           "ladder": [], "prior_week": None, "prior_year_week": prior_year_week(week)}
    if not name or week is None:
        return out

    # -- 1. long history for this queue (the prompt asks for ~104 weeks) --
    cur.execute(
        f"SELECT TOP {int(WFM_HISTORY_WEEKS)} {', '.join(_HISTORY_COLS)} FROM {table} "
        f"WHERE Forecast_name = ? AND Fiscal_Week <= ? ORDER BY Fiscal_Week DESC",
        (name, week))
    cols = [d[0] for d in cur.description]
    out["history_104"] = [dict(zip(cols, r)) for r in cur.fetchall()][::-1]   # chronological

    # -- 2. a short window AFTER the target week, used ONLY to test whether an extreme
    #       value reverted immediately (the data-quality check). For a live current-week
    #       investigation these rows do not exist yet and the check degrades to
    #       "cannot judge" rather than guessing. --
    cur.execute(
        f"SELECT TOP 4 Fiscal_Week, Actual_Offered FROM {table} "
        f"WHERE Forecast_name = ? AND Fiscal_Week > ? ORDER BY Fiscal_Week ASC",
        (name, week))
    cols = [d[0] for d in cur.description]
    out["history_forward"] = [dict(zip(cols, r)) for r in cur.fetchall()]

    # -- 3. channel siblings: same locality, ALL channels, this week + the prior week --
    prior = None
    for h in reversed(out["history_104"]):
        if str(h.get("Fiscal_Week")) != str(week):
            prior = h.get("Fiscal_Week")
            break
    out["prior_week"] = prior

    dims = [d for d in CHANNEL_SIBLING_DIMS if key.get(d) not in (None, "")]
    if dims:
        where = " AND ".join(f"{d} = ?" for d in dims)
        weeks = [week] if prior is None else [week, prior]
        marks = ", ".join("?" for _ in weeks)
        cur.execute(
            f"SELECT Fiscal_Week, channel, Forecast_name, Actual_Offered, fcst_offered "
            f"FROM {table} WHERE {where} AND Fiscal_Week IN ({marks})",
            tuple([key[d] for d in dims] + weeks))
        cols = [d[0] for d in cur.description]
        out["channel_sibling_rows"] = [dict(zip(cols, r)) for r in cur.fetchall()]

    # -- 4. the investigation ladder: adherence recomputed at each level, same week --
    ladder = []
    for label, group in _LADDER_LEVELS:
        if any(key.get(g) in (None, "") for g in group):
            continue
        where = " AND ".join(f"{g} = ?" for g in group)
        cur.execute(
            f"SELECT SUM(Actual_Offered), SUM(fcst_offered), COUNT(*) FROM {table} "
            f"WHERE Fiscal_Week = ? AND {where} "
            f"AND fcst_offered IS NOT NULL AND fcst_offered <> 0",
            tuple([week] + [key[g] for g in group]))
        row = cur.fetchone()
        if not row or row[1] in (None, 0):
            continue
        act, fc, n = float(row[0] or 0), float(row[1]), int(row[2] or 0)
        ladder.append({
            "level": label,
            "scope": " / ".join(str(key[g]) for g in group),
            "actual_offered": round(act, 1),
            "fcst_offered": round(fc, 1),
            "adherence_pct": round(adherence_pct(act, fc), 1),
            "queue_weeks_in_scope": n,
        })
    out["ladder"] = ladder
    return out
