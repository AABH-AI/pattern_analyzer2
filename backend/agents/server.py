# -*- coding: utf-8 -*-
"""A server for the multi-agent RCA, so it can be driven from a browser.

    cd backend
    python -m uvicorn agents.server:app --port 9402
    then open  http://localhost:9402/

WHY ITS OWN APP AND ITS OWN PORT
--------------------------------
`sql_backend` on 9000 serves the approved RCA engine, which is being used for a business demo.
This is experimental. A separate app on a separate port means nothing here can affect that, and
this can be restarted freely while the engine keeps serving.

It does reuse the engine's deterministic evidence -- `investigate_spec` with `interrogate=False`
-- because that is the point: every figure still comes from the 33 modules, and the agents only
write prose around figures they were handed.
"""
import json
import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
ROOT = BACKEND.parent
UI = ROOT / "agents_console.html"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents import graph, models as M                      # noqa: E402
from agents.run_agents import scope_evidence               # noqa: E402

# --------------------------------------------------------------------------------------------
# Holidays come from SQL here, not the JSON extract.
#
# The engine has always read backend/wfm/context_repository/holiday_master.json, a build-time
# extract of an Excel workbook. Carrying a second copy of a calendar that is already published
# to SQL is inefficient and lets the two drift -- and they had: dbo.Holiday_Master was missing
# 945 observed and substitute dates because its loader keyed on (country, week, name) and
# dropped the extra dates. Those were appended and verified, so SQL now matches the extract row
# for row: 10,702 rows both sides.
#
# A factory, not a cursor: this backend opens a connection per request, so a cursor cached at
# startup would be dead by the second investigation.
# --------------------------------------------------------------------------------------------
HOLIDAY_SOURCE = (os.environ.get("RCA_HOLIDAY_SOURCE") or "sql").strip().lower()


def _enable_sql_holidays():
    """Point the holiday repository at SQL. Returns what it reports about itself."""
    from sql_backend import connect
    from wfm.context_repository import holiday_calendar as cal
    cfg = _cfg()
    if HOLIDAY_SOURCE != "sql":
        cal.use_sql(None)
        return cal.loaded()
    cal.use_sql(lambda: connect(cfg).cursor())
    return cal.loaded()


app = FastAPI(title="Multi-agent RCA")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


def _cfg():
    from sql_backend import load_config
    return load_config()


def _groq_key(cfg, supplied=None):
    """A key supplied with the request wins, so the UI can override the file."""
    supplied = (supplied or "").strip()
    if supplied:
        return supplied, "supplied by the browser"
    env = (os.environ.get("GROQ_API_KEY") or "").strip()
    if env:
        return env, "GROQ_API_KEY"
    llm = (cfg or {}).get("llm") or {}
    for slot in ("primary", "secondary"):
        s = llm.get(slot) or {}
        if s.get("provider") == "groq" and s.get("api_key"):
            return s["api_key"], "config.json -> llm.%s" % slot
    return "", "not found"


@app.on_event("startup")
def _startup():
    try:
        info = _enable_sql_holidays()
        print("[holiday] requested=%s served_from=%s rows=%s country_weeks=%s"
              % (HOLIDAY_SOURCE, info.get("served_from"), info.get("active_rows"),
                 info.get("country_weeks")))
        if info.get("sql_error"):
            print("[holiday] SQL load failed, fell back to the extract: %s" % info["sql_error"])
    except Exception as exc:
        print("[holiday] setup skipped: %s: %s" % (type(exc).__name__, exc))


@app.get("/api/health")
def health():
    cfg = _cfg()
    key, source = _groq_key(cfg)
    from wfm.context_repository import holiday_calendar as cal
    hol = cal.loaded()
    return {"status": "ok",
            "holiday": {"requested": HOLIDAY_SOURCE,
                        "served_from": hol.get("served_from"),
                        "source": hol.get("source"),
                        "rows": hol.get("active_rows"),
                        "country_weeks": hol.get("country_weeks"),
                        "sql_error": hol.get("sql_error")},
            "sql_table": (cfg.get("sql") or {}).get("table"),
            "groq_key_present": bool(key), "groq_key_source": source,
            "roles": {r: M.role(r)["model"] for r in M.ROLES},
            "config_problems": M.audit_config(cfg)}


@app.get("/api/models")
def models():
    """The models a role may be switched to. Live from the provider, not a hardcoded list."""
    cfg = _cfg()
    key, _ = _groq_key(cfg)
    available, report = M.verify_live(key)
    # Only chat-capable models can serve an agent role. Whisper is speech-to-text, Orpheus is
    # text-to-speech, prompt-guard is an injection classifier -- offering them as an agent model
    # would produce a confusing failure rather than an obvious one.
    NOT_CHAT = ("whisper", "orpheus", "prompt-guard")
    chat = sorted(m for m in available if not any(x in m for x in NOT_CHAT))
    return {"chat_models": chat, "all": sorted(available), "verify": report,
            "roles": {r: M.role(r)["model"] for r in M.ROLES}}


@app.get("/api/candidates")
def candidates(limit: int = 25):
    """Real queue-weeks worth investigating: the biggest recent misses."""
    from sql_backend import connect
    cfg = _cfg()
    table = (cfg.get("sql") or {}).get("table")
    try:
        cur = connect(cfg).cursor()
        cur.execute(
            "SELECT TOP %d Forecast_name, Fiscal_Week, Country, channel, "
            "       fcst_offered, Actual_Offered "
            "  FROM %s "
            " WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND fcst_offered > 3000 "
            "   AND Country IS NOT NULL AND Country <> '' "
            "   AND ABS(1 - Actual_Offered / fcst_offered) > 0.25 "
            " ORDER BY ABS(Actual_Offered - fcst_offered) DESC" % (int(limit), table))
        rows = []
        for name, wk, country, ch, fc, ac in cur.fetchall():
            rows.append({"queue": name, "fiscal_week": int(wk), "country": country,
                         "channel": ch, "forecast": round(float(fc)),
                         "actual": round(float(ac)),
                         "gap": round(abs(float(ac) - float(fc))),
                         "adherence_pct": round((1 - float(ac) / float(fc)) * 100, 1)})
        return {"count": len(rows), "candidates": rows}
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail="SQL unavailable: %s: %s. Is the VPN connected?"
                                   % (type(exc).__name__, str(exc)[:160]))


@app.post("/api/run")
def run(body: dict):
    """Compute the deterministic evidence, then run the four agents over a scoped slice."""
    from sql_backend import connect
    from wfm import fetch_wfm_context, investigate_spec
    from wfm.common import adherence_pct

    cfg = _cfg()
    key, key_source = _groq_key(cfg, body.get("api_key"))
    if not key:
        raise HTTPException(status_code=503, detail="No Groq API key. %s" % key_source)

    queue = (body.get("queue") or "").strip()
    try:
        week = int(body.get("fiscal_week"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="fiscal_week must be an integer")
    if not queue:
        raise HTTPException(status_code=400, detail="queue is required")

    table = (cfg.get("sql") or {}).get("table")
    try:
        cur = connect(cfg).cursor()
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail="SQL unavailable: %s. Is the VPN connected?" % str(exc)[:160])
    cur.execute("SELECT * FROM %s WHERE Forecast_name = ? AND Fiscal_Week = ?" % table,
                (queue, week))
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no row for %s FW%s" % (queue, week))
    f = dict(zip([d[0] for d in cur.description], r))
    a, fc = f.get("Actual_Offered"), f.get("fcst_offered")

    t0 = time.time()
    bundle = {"target": {
        "key": {k: f.get(k) for k in ("Forecast_name", "Fiscal_Week", "Region", "SubRegion",
                                      "Country", "channel", "business_org", "Offering")},
        "fields": f,
        "computed": {"actual": a, "forecast": fc, "adherence_pct": adherence_pct(a, fc)}}}
    wfm_ctx = fetch_wfm_context(cur, table, bundle["target"]["key"])
    finding = investigate_spec(bundle, {}, wfm_ctx, grain="weekly", interrogate=False)
    deterministic_seconds = time.time() - t0

    ev, figures = scope_evidence(finding, cursor=cur, fact_table=table,
                                 queue=queue, fiscal_week=week)
    whole = len(json.dumps(finding, default=str))
    scoped = len(json.dumps(ev, default=str))

    # Where every piece of this came from. Without this the ingestion is invisible and someone
    # reasonably assumes the joins are not happening.
    from wfm.context_repository import holiday_calendar as cal
    hol_resp = finding.get("holiday_response") or {}
    ingestion = {
        "input_to_ml": {
            "table": table, "target_columns": len(f),
            "history_rows": len(wfm_ctx.get("history_104") or []),
            "forward_rows": len(wfm_ctx.get("history_forward") or []),
            "prior_week": wfm_ctx.get("prior_week"),
            "prior_year_week": wfm_ctx.get("prior_year_week"),
        },
        "cqn": {
            "table": "dbo.CQN_Mapping",
            "source": wfm_ctx.get("cqn_source"),
            "cqn_names": wfm_ctx.get("cqn_names"),
            "sibling_rows_same_week": len(wfm_ctx.get("channel_sibling_rows") or []),
            "ladder_levels": len(wfm_ctx.get("ladder") or []),
        },
        "holiday": {
            "served_from": cal.configured_source(),
            "source": (cal.loaded() or {}).get("source"),
            "rows": (cal.loaded() or {}).get("active_rows"),
            "availability": hol_resp.get("availability"),
            "country_resolved": hol_resp.get("country_resolved"),
            "phase": hol_resp.get("phase"),
            "holidays_in_week": ((hol_resp.get("holidays_in_target_week") or {})
                                 .get("canonical_names")),
        },
    }

    headline = ("%s, FW%s: %s contacts %s plan (%s planned, %s handled), adherence %+.1f%%."
                % (queue, week, format(round(abs(a - fc)), ","),
                   "over" if a > fc else "under", format(round(fc), ","),
                   format(round(a), ","), adherence_pct(a, fc)))

    overrides = {}
    for role in M.ROLES:
        m = (body.get("models") or {}).get(role)
        if m:
            overrides[role] = {"model": m}

    state = graph.run(queue, week, ev, figures, headline, key, overrides=overrides)
    ok, why = graph.publishable(state)

    return {
        "queue": queue, "fiscal_week": week, "headline": headline,
        "case": {"forecast": round(float(fc)), "actual": round(float(a)),
                 "gap": round(abs(float(a) - float(fc))),
                 "adherence_pct": round(adherence_pct(a, fc), 1),
                 "country": f.get("Country"), "channel": f.get("channel")},
        "ingestion": ingestion,
        "scoped_evidence": ev,
        "permitted_figures": sorted(figures),
        "context": {"whole_finding_chars": whole, "scoped_chars": scoped,
                    "scoped_share_pct": round(100.0 * scoped / whole, 2),
                    "whole_finding_tokens_approx": whole // 4,
                    "scoped_tokens_approx": scoped // 4},
        "analyst": state.analyst, "challenger": state.challenger,
        "report": state.report, "verdict": state.verdict,
        "publishable": ok, "publish_note": why,
        "summary": state.summary(), "calls": state.calls,
        "deterministic_seconds": round(deterministic_seconds, 2),
        "agent_seconds": state.timings.get("total"),
        "key_source": key_source,
        "models_used": {r: (overrides.get(r) or {}).get("model") or M.role(r)["model"]
                        for r in M.ROLES},
    }


# --------------------------------------------------------------------------------------------
# Filters and trends
#
# The approved console builds its filter panel over the whole loaded table in the browser. That
# does not scale to 114,436 rows, so these do the same work in SQL: DISTINCT per dimension,
# narrowed by whatever is already selected, so the choices always reflect rows that actually
# exist rather than offering combinations with nothing behind them.
#
# Every value is bound as a parameter. Dimension NAMES are whitelisted against FILTER_DIMS
# before being interpolated, because a column name cannot be a bind parameter.
# --------------------------------------------------------------------------------------------
FILTER_DIMS = ["Region", "SubRegion", "Country", "channel", "Offering",
               "business_org", "Forecaster", "Volume_Category", "Forecast_name"]


def _where(sel):
    """(sql_fragment, params) from a {dimension: value} selection. Unknown keys are ignored."""
    clauses, params = [], []
    for dim in FILTER_DIMS + ["Fiscal_Week"]:
        v = (sel or {}).get(dim)
        if v in (None, "", "ALL"):
            continue
        clauses.append("[%s] = ?" % dim)
        params.append(int(v) if dim == "Fiscal_Week" else v)
    return (" AND ".join(clauses), params)


@app.post("/api/filters")
def filters(body: dict = None):
    """Distinct values per dimension, narrowed by the current selection.

    Cascading: choose a Region and the Country list shrinks to countries in it. A dimension is
    excluded from its own narrowing, so changing your mind never empties the list you are
    looking at.
    """
    from sql_backend import connect
    cfg = _cfg()
    table = (cfg.get("sql") or {}).get("table")
    sel = (body or {}).get("selection") or {}
    try:
        cur = connect(cfg).cursor()
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail="SQL unavailable: %s. Is the VPN connected?" % str(exc)[:150])

    out = {}
    for dim in FILTER_DIMS:
        frag, params = _where({k: v for k, v in sel.items() if k != dim})
        q = ("SELECT DISTINCT [%s] FROM %s WHERE [%s] IS NOT NULL AND [%s] <> %s"
             % (dim, table, dim, dim, "''"))
        if frag:
            q += " AND " + frag
        q += " ORDER BY [%s]" % dim
        cur.execute(q, params)
        out[dim] = [r[0] for r in cur.fetchall() if r[0] not in (None, "")][:600]

    frag, params = _where({k: v for k, v in sel.items() if k != "Fiscal_Week"})
    q = "SELECT DISTINCT Fiscal_Week FROM %s WHERE Fiscal_Week IS NOT NULL" % table
    if frag:
        q += " AND " + frag
    cur.execute(q + " ORDER BY Fiscal_Week DESC", params)
    out["Fiscal_Week"] = [int(r[0]) for r in cur.fetchall()]

    frag, params = _where(sel)
    q = "SELECT COUNT(*) FROM %s" % table
    if frag:
        q += " WHERE " + frag
    cur.execute(q, params)
    return {"options": out, "matching_rows": cur.fetchone()[0], "dimensions": FILTER_DIMS}


@app.post("/api/search")
def search(body: dict = None):
    """Queue-weeks matching the filters, biggest miss first."""
    from sql_backend import connect
    cfg = _cfg()
    table = (cfg.get("sql") or {}).get("table")
    body = body or {}
    sel = body.get("selection") or {}
    limit = max(1, min(int(body.get("limit") or 50), 300))
    min_forecast = float(body.get("min_forecast") or 0)
    min_adh = float(body.get("min_abs_adherence") or 0)

    frag, params = _where(sel)
    clauses = ["fcst_offered IS NOT NULL", "Actual_Offered IS NOT NULL", "fcst_offered > 0"]
    if frag:
        clauses.append(frag)
    if min_forecast:
        clauses.append("fcst_offered >= ?")
        params.append(min_forecast)
    if min_adh:
        clauses.append("ABS(1 - Actual_Offered / fcst_offered) * 100 >= ?")
        params.append(min_adh)
    try:
        cur = connect(cfg).cursor()
        cur.execute(
            "SELECT TOP %d Forecast_name, Fiscal_Week, Region, SubRegion, Country, channel, "
            "       Offering, fcst_offered, Actual_Offered, Holiday_Count "
            "  FROM %s WHERE %s ORDER BY ABS(Actual_Offered - fcst_offered) DESC"
            % (limit, table, " AND ".join(clauses)), params)
        rows = []
        for (nm, wk, reg, sub, ctry, ch, off, fc, ac, hol) in cur.fetchall():
            fc, ac = float(fc), float(ac)
            rows.append({"queue": nm, "fiscal_week": int(wk), "region": reg, "subregion": sub,
                         "country": ctry, "channel": ch, "offering": off,
                         "forecast": round(fc), "actual": round(ac),
                         "gap": round(abs(ac - fc)),
                         "adherence_pct": round((1 - ac / fc) * 100, 1),
                         "holiday_count": hol})
        return {"count": len(rows), "results": rows}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="query failed: %s" % str(exc)[:200])


@app.get("/api/trend")
def trend(queue: str, weeks: int = 52, upto: int = 0):
    """Forecast, actual and adherence per fiscal week for one queue -- what the charts draw.

    Straight from SQL. No model is involved in any point on these lines.
    """
    from sql_backend import connect
    cfg = _cfg()
    table = (cfg.get("sql") or {}).get("table")
    try:
        cur = connect(cfg).cursor()
        params = [queue]
        q = ("SELECT TOP %d Fiscal_Week, fcst_offered, Actual_Offered, Holiday_Count "
             "  FROM %s WHERE Forecast_name = ? AND fcst_offered IS NOT NULL "
             "   AND Actual_Offered IS NOT NULL" % (max(4, min(int(weeks), 209)), table))
        if upto:
            q += " AND Fiscal_Week <= ?"
            params.append(int(upto))
        cur.execute(q + " ORDER BY Fiscal_Week DESC", params)
        pts = []
        for wk, fc, ac, hol in cur.fetchall():
            fc, ac = float(fc), float(ac)
            pts.append({"fiscal_week": int(wk), "forecast": round(fc), "actual": round(ac),
                        "adherence_pct": round((1 - ac / fc) * 100, 1) if fc else None,
                        "holiday": bool(hol)})
        pts.reverse()
        adh = [p["adherence_pct"] for p in pts if p["adherence_pct"] is not None]
        return {"queue": queue, "count": len(pts), "points": pts, "stats": {
            "mean_abs_adherence": round(sum(abs(a) for a in adh) / len(adh), 1) if adh else None,
            "weeks_over_10pct": len([a for a in adh if abs(a) > 10]),
            "worst": max(adh, key=abs) if adh else None,
            "holiday_weeks": len([p for p in pts if p["holiday"]])}}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="trend query failed: %s" % str(exc)[:200])


@app.post("/api/breakdown")
def breakdown(body: dict = None):
    """Mean absolute adherence grouped by one dimension, for the comparison bars."""
    from sql_backend import connect
    cfg = _cfg()
    table = (cfg.get("sql") or {}).get("table")
    body = body or {}
    dim = body.get("dimension") or "Region"
    if dim not in FILTER_DIMS:
        raise HTTPException(status_code=400,
                            detail="dimension must be one of %s" % FILTER_DIMS)
    frag, params = _where(body.get("selection") or {})
    clauses = ["fcst_offered > 0", "Actual_Offered IS NOT NULL",
               "[%s] IS NOT NULL" % dim, "[%s] <> %s" % (dim, "''")]
    if frag:
        clauses.append(frag)
    try:
        cur = connect(cfg).cursor()
        cur.execute(
            "SELECT TOP 20 [%s], COUNT(*), "
            "       AVG(ABS(1 - Actual_Offered / fcst_offered) * 100), "
            "       SUM(ABS(Actual_Offered - fcst_offered)) "
            "  FROM %s WHERE %s GROUP BY [%s] "
            " ORDER BY AVG(ABS(1 - Actual_Offered / fcst_offered) * 100) DESC"
            % (dim, table, " AND ".join(clauses), dim), params)
        return {"dimension": dim, "groups": [
            {"value": v, "rows": int(n),
             "mean_abs_adherence_pct": round(float(m), 1),
             "total_gap_contacts": round(float(g))}
            for v, n, m, g in cur.fetchall()]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="breakdown failed: %s" % str(exc)[:200])


# --------------------------------------------------------------------------------------------
# Where the data comes from
#
# Nothing here ingests anything. These are the scripts that do, run by hand when new data
# arrives -- typically weekly. Recording them next to the table each one fills means a planner
# can see what is loaded and how current it is without reading any code.
# --------------------------------------------------------------------------------------------
DATA_SOURCES = [
    {"name": "Forecast and actual volumes",
     "table": "dbo.Input_To_ML_Full_138_Trimmed",
     "loaded_by": "backend/upload_excel_to_sql.py",
     "from_file": "the weekly Input_To_ML workbook (.xlsx or .csv)",
     "how": "python upload_excel_to_sql.py --excel <path>",
     "week_column": "Fiscal_Week",
     "what_for": "every forecast, every actual. The figures the whole analysis rests on."},
    {"name": "Queue grouping (CQN)",
     "table": "dbo.CQN_Mapping",
     "loaded_by": "backend/upload_cqn_mapping.py",
     "from_file": "the CQN and FC mapping workbook",
     "how": "python upload_cqn_mapping.py --excel <path>",
     "week_column": None,
     "what_for": "which queues belong together, so a queue can be compared with its peers "
                 "in the same week."},
    {"name": "Holiday calendar",
     "table": "dbo.Holiday_Master",
     "loaded_by": "backend/load_holiday_master.py then load_holiday_to_sql.py",
     "from_file": "FC_RCA_Holiday_Master_Production.xlsx",
     "how": "python load_holiday_master.py <xlsx>  then  python load_holiday_to_sql.py",
     "week_column": "fiscal_week",
     "what_for": "which weeks contain a holiday, in which country, and how far its effect "
                 "reaches."},
    {"name": "Holiday name groups",
     "table": "dbo.Holiday_Semantic_Group",
     "loaded_by": "backend/build_holiday_semantic_groups.py",
     "from_file": "derived from the holiday calendar",
     "how": "python build_holiday_semantic_groups.py",
     "week_column": None,
     "what_for": "recognises that two spellings are the same holiday, so its effect is not "
                 "counted twice."},
    {"name": "Fiscal calendar",
     "table": "dbo.Fiscal_Calendar_Week",
     "loaded_by": "backend/load_holiday_to_sql.py",
     "from_file": "derived from the holiday workbook",
     "week_column": "fiscal_week",
     "how": "loaded alongside the holiday calendar",
     "what_for": "which real dates each fiscal week covers."},
    {"name": "Country name matching",
     "table": "dbo.Holiday_Country_Alias",
     "loaded_by": "backend/load_holiday_to_sql.py",
     "from_file": "derived",
     "week_column": None,
     "how": "loaded alongside the holiday calendar",
     "what_for": "matches country names in the volume data to the calendar's names."},
]


@app.get("/api/sources")
def sources():
    """Every table this console reads, how current it is, and what loads it."""
    from sql_backend import connect
    cfg = _cfg()
    live_table = (cfg.get("sql") or {}).get("table")
    try:
        cur = connect(cfg).cursor()
    except Exception as exc:
        return {"ok": False,
                "reason": "Cannot reach the database. %s" % str(exc)[:150],
                "sources": DATA_SOURCES}
    out = []
    for src in DATA_SOURCES:
        row = dict(src)
        row["in_use"] = (src["table"] == live_table)
        try:
            cur.execute("SELECT COUNT(*) FROM %s" % src["table"])
            row["rows"] = int(cur.fetchone()[0])
            if src.get("week_column"):
                cur.execute("SELECT MIN([%s]), MAX([%s]) FROM %s"
                            % (src["week_column"], src["week_column"], src["table"]))
                lo, hi = cur.fetchone()
                row["earliest_week"] = int(lo) if lo is not None else None
                row["latest_week"] = int(hi) if hi is not None else None
            row["present"] = True
        except Exception as exc:
            row["present"] = False
            row["rows"] = None
            row["problem"] = str(exc)[:120]
        out.append(row)
    return {"ok": True, "sources": out, "reads_from": live_table}


@app.get("/")
def index():
    if not UI.exists():
        raise HTTPException(status_code=404, detail="agents_console.html not found at %s" % UI)
    return FileResponse(str(UI))
