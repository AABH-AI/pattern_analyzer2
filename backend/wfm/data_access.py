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

# The authoritative Combined-Queue mapping, loaded by backend/upload_cqn_mapping.py.
# If the table is absent the engine silently falls back to the locality proxy.
CQN_MAP_TABLE = "dbo.CQN_Mapping"

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
    # Offering is a real rung of the spec's investigation order (Country -> Offering ->
    # Channel) and was missing. A miss confined to one support tier within a country is a
    # different finding from one spread across all tiers, and jumping Country straight to
    # Channel hid that. Channel now nests INSIDE Offering so each row is a strict subset.
    ("Offering", ["business_org", "Region", "SubRegion", "Country", "Offering"]),
    ("Channel", ["business_org", "Region", "SubRegion", "Country", "Offering", "channel"]),
)


def fetch_wfm_context(cur, table, key, map_table=CQN_MAP_TABLE):
    """Fetch the deeper context the WFM prompt needs.

    key = {"Forecast_name", "Fiscal_Week", "Region", "SubRegion", "Country",
           "channel", "business_org"}

    Returns raw blocks only -- every derived number is computed by the analyzer
    modules, never here.
    """
    name = key.get("Forecast_name")
    week = key.get("Fiscal_Week")
    out = {"history_104": [], "history_forward": [], "channel_sibling_rows": [],
           "ladder": [], "prior_week": None, "prior_year_week": prior_year_week(week),
           "cqn_names": [], "cqn_source": "proxy"}
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

    # -- 3. channel siblings: this week + the prior week --
    prior = None
    for h in reversed(out["history_104"]):
        if str(h.get("Fiscal_Week")) != str(week):
            prior = h.get("Fiscal_Week")
            break
    out["prior_week"] = prior
    weeks = [week] if prior is None else [week, prior]
    marks = ", ".join("?" for _ in weeks)

    # Prefer the AUTHORITATIVE Combined Queue from dbo.CQN_Mapping when it is loaded. The
    # mapping workbook settled the definition: 35 of 331 CQNs span more than one channel, so
    # "migration between channels within a CQN" is real and this is the correct grouping.
    # A Forecast_Name can belong to MORE THAN ONE CQN (69 of 442 do -- vendor-site splits such
    # as Concentrix vs CGS), so we take the UNION of every CQN it belongs to and record them.
    out["cqn_names"] = []
    out["cqn_source"] = "proxy"
    try:
        cur.execute(f"SELECT DISTINCT Combined_Queue_Name FROM {map_table} "
                    f"WHERE Forecast_Name = ? AND Combined_Queue_Name IS NOT NULL", (name,))
        out["cqn_names"] = [r[0] for r in cur.fetchall()]
    except Exception:
        out["cqn_names"] = []          # mapping table not loaded; fall back to the proxy

    if out["cqn_names"]:
        cqn_marks = ", ".join("?" for _ in out["cqn_names"])
        cur.execute(
            f"SELECT d.Fiscal_Week, d.channel, d.Forecast_name, d.Actual_Offered, d.fcst_offered "
            f"FROM {table} d "
            f"WHERE d.Fiscal_Week IN ({marks}) AND EXISTS ("
            f"  SELECT 1 FROM {map_table} m WHERE m.Forecast_Name = d.Forecast_name "
            f"    AND m.Combined_Queue_Name IN ({cqn_marks}))",
            tuple(weeks + out["cqn_names"]))
        cols = [d[0] for d in cur.description]
        out["channel_sibling_rows"] = [dict(zip(cols, r)) for r in cur.fetchall()]
        out["cqn_source"] = "mapping"
    else:
        dims = [d for d in CHANNEL_SIBLING_DIMS if key.get(d) not in (None, "")]
        if dims:
            where = " AND ".join(f"{d} = ?" for d in dims)
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
