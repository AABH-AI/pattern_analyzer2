# -*- coding: utf-8 -*-
"""
Local backend for the Demand Pattern RCA Agent.

- GET  /api/health           -> {status, configured, table}
- GET  /api/data             -> {columns, rows, count}   (runs SELECT * FROM <table>)
- GET  /api/queue-context    -> {target_row, history_rows, peer_rows} — scoped fetch for
  RCA: queries SQL Server directly for just one queue's own row, its history, and its
  CQN peers, instead of filtering the whole in-browser table.
- POST /api/rca-investigate  -> InvestigationResponse (see rca_investigate.py) — the
  LLM Investigation Engine proxy. Console posts a generic ContextBundle here; this
  endpoint never runs on-page/client-side so a real provider key never has to sit in
  the (public) rca_console.html file.
- everything else  -> serves the static UI from the repo root, so opening
  http://localhost:9000/rca_console.html and clicking "Investigate Root Cause"
  is a same-origin fetch.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn sql_backend:app --port 9000
Then open http://localhost:9000/rca_console.html  (or open the file directly;
CORS is open so the file:// page can still reach http://localhost:9000).

Connection details come from backend/config.json (see config.example.json).
config.json is gitignored so credentials are never committed.
"""
import json
import os
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from rca_investigate import investigate
from wfm import fetch_wfm_context, investigate_spec, investigate_wfm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent               # repo root, where the .html files live
CONFIG = HERE / "config.json"

app = FastAPI(title="Demand Pattern RCA - SQL connector")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# SECURITY: app.mount("/", StaticFiles(directory=ROOT)) below serves the whole
# repo root, which is also where backend/config.json (SQL + LLM credentials),
# backend/.env, and this Python source live. Without this guard, anyone who can
# reach the server can GET /backend/config.json and read live secrets in plain
# text. Block anything under backend/ (and dotfiles) before it ever reaches the
# static handler — the UI only ever needs the .html files at the repo root.
_BLOCKED_PREFIXES = ("/backend/", "/.git/")
_BLOCKED_EXACT = {"/.env"}
@app.middleware("http")
async def block_sensitive_paths(request: Request, call_next):
    path = request.url.path
    if path in _BLOCKED_EXACT or any(path.startswith(p) for p in _BLOCKED_PREFIXES):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return await call_next(request)


def load_config():
    """Config from backend/config.json, with environment variables taking
    precedence (so secrets can be injected in deployment without a file)."""
    cfg = {}
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    sql = dict(cfg.get("sql", {}))
    envmap = {"server": "SQL_SERVER", "database": "SQL_DATABASE", "table": "SQL_TABLE",
              "auth": "SQL_AUTH", "username": "SQL_USERNAME", "password": "SQL_PASSWORD",
              "driver": "SQL_DRIVER"}
    for key, env in envmap.items():
        v = os.environ.get(env)
        if v not in (None, ""):
            sql[key] = v
    if os.environ.get("SQL_ENCRYPT") is not None:
        sql["encrypt"] = os.environ["SQL_ENCRYPT"].lower() in ("1", "true", "yes")
    if os.environ.get("SQL_TRUST_CERT") is not None:
        sql["trust_server_certificate"] = os.environ["SQL_TRUST_CERT"].lower() in ("1", "true", "yes")
    if sql:
        cfg["sql"] = sql
    # llm: two named slots (primary = tried first, secondary = fallback), env vars take
    # precedence — same pattern as sql above. Both are OpenAI-compatible chat APIs. Which
    # provider is primary vs secondary is decided by config.json (or below); env-var
    # overrides are matched BY PROVIDER NAME to whichever slot currently holds that
    # provider, not to a fixed slot position — so re-ordering primary/secondary in
    # config.json (e.g. to make NVIDIA the priority provider) doesn't get silently undone
    # by GROQ_API_KEY/NVIDIA_API_KEY env vars assuming the old fixed positions.
    llm = dict(cfg.get("llm", {}))
    primary = dict(llm.get("primary", {}))
    secondary = dict(llm.get("secondary", {}))
    slots = {"primary": primary, "secondary": secondary}

    def _apply_env(provider_name, api_key_env, model_env):
        for slot in slots.values():
            if slot.get("provider") == provider_name:
                if os.environ.get(api_key_env):
                    slot["api_key"] = os.environ[api_key_env]
                if os.environ.get(model_env):
                    slot["model"] = os.environ[model_env]

    _apply_env("groq", "GROQ_API_KEY", "GROQ_MODEL")
    _apply_env("nvidia", "NVIDIA_API_KEY", "NVIDIA_MODEL")
    if primary:
        llm["primary"] = primary
    if secondary:
        llm["secondary"] = secondary
    if llm:
        cfg["llm"] = llm
    return cfg


def connect(cfg):
    import pyodbc
    c = cfg["sql"]
    driver = c.get("driver", "ODBC Driver 17 for SQL Server")
    if str(c.get("auth", "sql")).lower() == "windows":
        conn_str = f"DRIVER={{{driver}}};SERVER={c['server']};DATABASE={c['database']};Trusted_Connection=yes;"
    else:
        conn_str = (f"DRIVER={{{driver}}};SERVER={c['server']};DATABASE={c['database']};"
                    f"UID={c.get('username','')};PWD={c.get('password','')};")
    if c.get("encrypt") is not None:
        conn_str += f"Encrypt={'yes' if c['encrypt'] else 'no'};"
    if c.get("trust_server_certificate"):
        conn_str += "TrustServerCertificate=yes;"
    # LOGIN timeout and QUERY timeout are different things, and passing one value for both meant
    # an unreachable server took the full query timeout (measured: 30.3s) to report itself. That
    # is useless for the case it matters most in -- telling someone their VPN is down.
    #
    # `pyodbc.connect(timeout=...)` sets SQL_ATTR_LOGIN_TIMEOUT, so it bounds the LOGIN. The
    # per-statement timeout is a property set on the connection afterwards. Measured: the
    # connection-string `Connect Timeout` keyword is overridden by the kwarg, so it is the kwarg
    # that has to carry the short value.
    #
    # Short login timeout on purpose: an unreachable server is not slow, it is absent, and
    # waiting longer will not make it appear. The query timeout stays generous -- the reads this
    # app makes are legitimately heavy on a HEAP table.
    conn = pyodbc.connect(conn_str, timeout=int(c.get("login_timeout", 5)))
    conn.timeout = int(c.get("timeout", 30))
    return conn


def conv(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):   # date / datetime
        return v.isoformat()
    return v


@app.get("/api/health")
def health():
    cfg = load_config()
    sql = cfg.get("sql", {})
    return {"status": "ok", "configured": bool(sql.get("server")), "table": sql.get("table")}


@app.get("/api/data")
def data(limit: int = Query(0, ge=0, description="Optional TOP N; 0 = all rows")):
    cfg = load_config()
    sql = cfg.get("sql", {})
    if not sql.get("server") or sql.get("server", "").startswith("YOUR_"):
        raise HTTPException(status_code=503,
                            detail="SQL not configured. Copy backend/config.example.json to backend/config.json and fill in your server details.")
    table = sql.get("table", "dbo.Input_To_ML")
    try:
        conn = connect(cfg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not connect to SQL Server: {e}")
    try:
        cur = conn.cursor()
        top = f"TOP {int(limit)} " if limit else ""
        cur.execute(f"SELECT {top}* FROM {table}")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, (conv(v) for v in r))) for r in cur.fetchall()]
        return {"columns": cols, "rows": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        conn.close()


# --- Server-side filtering and refresh detection ------------------------------------------
# `/api/data` above ships the whole table: 114,436 rows, 7.3s, ~82.6 MB, on every page load,
# and the browser then filters it in JavaScript. The endpoints below let the SERVER do the
# filtering. Measured on the same instance, the console's default view (flagged rows in the
# current fiscal year) is 6,264 rows, 55 ms and 3.9 MB -- 27x faster and 21x smaller.
#
# `/api/data` is deliberately LEFT IN PLACE. It is what the file-upload-free bulk path and the
# existing UI still call, and removing it in the same change that adds the replacement would
# make a regression impossible to bisect.

def _sql_or_503(cfg):
    """Connect, or fail with a message that says what to do about it.

    A dropped VPN is the common case and it must not look like an application error: the caller
    needs to be told to reconnect, not shown a stack trace. 503 (not 500) because the service is
    reachable and the DEPENDENCY is not -- that distinction is what lets the console decide
    between 'retry' and 'report a bug'.
    """
    sql = cfg.get("sql", {})
    if not sql.get("server") or str(sql.get("server", "")).startswith("YOUR_"):
        raise HTTPException(status_code=503, detail={
            "code": "sql_not_configured",
            "message": "SQL is not configured. Copy backend/config.example.json to "
                       "backend/config.json and fill in your server details."})
    try:
        return connect(cfg)
    except Exception as e:
        raise HTTPException(status_code=503, detail={
            "code": "sql_unreachable",
            "message": "Cannot reach the database. Connect to the VPN and try again.",
            "server": sql.get("server"), "database": sql.get("database"),
            "driver": sql.get("driver"), "error": str(e)})


def _freshness(cur, cfg):
    from wfm import data_freshness
    sql = cfg.get("sql", {})
    refresh = sql.get("refresh") or {}
    probe = data_freshness.probe(cur, sql.get("table", "dbo.Input_To_ML"),
                                 load_column=refresh.get("load_column"))
    probe["cadence"] = refresh.get("cadence")
    probe["describe"] = data_freshness.describe(probe, refresh.get("cadence"))
    return probe


@app.get("/api/data-freshness")
def data_freshness_endpoint(token: str = Query("", description="The token this client currently holds")):
    """Has the source data been reloaded since the caller's view was built?

    Cheap by design (~100 ms, aggregates only) so a console can poll it without cost.
    """
    from wfm import data_freshness
    cfg = load_config()
    conn = _sql_or_503(cfg)
    try:
        probe = _freshness(conn.cursor(), cfg)
        return {"freshness": probe, "compare": data_freshness.compare(token or None, probe)}
    finally:
        conn.close()


@app.get("/api/rows")
def rows(week_from: str = Query("", description="Lowest fiscal week to include, e.g. 202701"),
         week_to: str = Query("", description="Highest fiscal week to include"),
         last_weeks: int = Query(0, ge=0, description="Window of the last N weeks holding data; "
                                                      "ignored when week_from is given"),
         flagged_only: int = Query(0, description="1 = only rows whose |adherence| exceeds the band"),
         band: float = Query(10.0, description="Adherence band in percent, used when flagged_only=1"),
         region: str = "", subregion: str = "", country: str = "", offering: str = "",
         channel: str = "", business_org: str = "", forecast_name: str = "",
         forecaster: str = "", volume_category: str = "",
         limit: int = Query(5000, ge=1, description="Page size"),
         offset: int = Query(0, ge=0, description="Rows to skip"),
         include_total: int = Query(1, description="1 = also return the unpaged row count")):
    """A filtered, paged slice of the demand table, with adherence computed in SQL.

    Multi-value filters: repeat a value comma-separated, e.g. `region=EMEA,APJ`.
    """
    from wfm import row_query as rq
    cfg = load_config()
    table = cfg.get("sql", {}).get("table", "dbo.Input_To_ML")

    def multi(v):
        return [p.strip() for p in str(v).split(",") if p.strip()] if v else None

    filters = {"Region": multi(region), "SubRegion": multi(subregion), "Country": multi(country),
               "Offering": multi(offering), "channel": multi(channel),
               "business_org": multi(business_org), "Forecast_name": multi(forecast_name),
               "Forecaster": multi(forecaster), "Volume_Category": multi(volume_category)}
    conn = _sql_or_503(cfg)
    try:
        cur = conn.cursor()
        # `last_weeks` is resolved against the weeks that actually hold data, not by arithmetic
        # on the week number -- see row_query.resolve_last_weeks. An explicit week_from always
        # wins, so a caller that states a window cannot have it silently overridden.
        resolved_from = week_from or None
        if not resolved_from and last_weeks:
            resolved_from = rq.resolve_last_weeks(cur, table, last_weeks)
        where, params = rq.build_where(filters, resolved_from, week_to or None,
                                       flagged_only=bool(flagged_only), band=band)
        sql_rows = rq.rows_sql(table, where, limit=limit, offset=offset)
    except rq.FilterError as e:
        conn.close()
        raise HTTPException(status_code=400, detail={"code": "bad_filter", "message": str(e)})

    try:
        out = {"rows": [], "count": 0, "total": None, "limit": limit, "offset": offset,
               "week_from": resolved_from, "week_to": week_to or None}
        if include_total:
            cur.execute(rq.count_sql(table, where), params)
            out["total"] = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(sql_rows, params)
        cols = [d[0] for d in cur.description]
        out["columns"] = cols
        out["rows"] = [dict(zip(cols, (conv(v) for v in r))) for r in cur.fetchall()]
        out["count"] = len(out["rows"])
        out["has_more"] = (out["total"] is not None and offset + out["count"] < out["total"])
        # Every slice carries the token of the load it came from. A client that later sees a
        # different token knows its view is stale WITHOUT having to re-fetch the rows to notice.
        out["freshness"] = _freshness(cur, cfg)
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        conn.close()


@app.get("/api/facets")
def facets(column: str = Query(..., description="Filter column to enumerate"),
           week_from: str = "", week_to: str = "",
           flagged_only: int = 0, band: float = 10.0):
    """Distinct values (and counts) for one filter column, so the console can build its
    dropdowns without downloading the table."""
    from wfm import row_query as rq
    cfg = load_config()
    table = cfg.get("sql", {}).get("table", "dbo.Input_To_ML")
    try:
        where, params = rq.build_where(None, week_from or None, week_to or None,
                                       flagged_only=bool(flagged_only), band=band)
        sql_txt = rq.facets_sql(table, column, where)
    except rq.FilterError as e:
        raise HTTPException(status_code=400, detail={"code": "bad_filter", "message": str(e)})
    conn = _sql_or_503(cfg)
    try:
        cur = conn.cursor()
        cur.execute(sql_txt, params)
        return {"column": column,
                "values": [{"value": conv(r[0]), "count": int(r[1] or 0)} for r in cur.fetchall()]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        conn.close()


@app.get("/api/queue-context")
def queue_context(forecast_name: str, fiscal_week: str, region: str = "", subregion: str = "",
                   country: str = "", channel: str = "", history_cap: int = 13, peers_cap: int = 15):
    """
    Scoped fetch for the RCA Investigation feature: queries SQL Server directly for
    ONLY the rows relevant to one queue — its own row, its prior-week history (same
    Forecast_name), and same-week CQN peers (same Region/SubRegion/Country/Channel,
    different Forecast_name) — instead of the console filtering an already fully
    loaded in-browser table. Used when the console's data source is SQL
    (window.SRC==='sql'); file-upload mode has no SQL connection to query and keeps
    filtering the in-browser rows.
    """
    cfg = load_config()
    sql = cfg.get("sql", {})
    if not sql.get("server") or sql.get("server", "").startswith("YOUR_"):
        raise HTTPException(status_code=503, detail="SQL not configured.")
    table = sql.get("table", "dbo.Input_To_ML")
    try:
        conn = connect(cfg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not connect to SQL Server: {e}")
    try:
        cur = conn.cursor()

        cur.execute(f"SELECT * FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ?",
                    (forecast_name, fiscal_week))
        cols = [d[0] for d in cur.description]
        target_rows = [dict(zip(cols, (conv(v) for v in row))) for row in cur.fetchall()]

        cur.execute(
            f"SELECT TOP {int(history_cap)} * FROM {table} "
            f"WHERE Forecast_name = ? AND Fiscal_Week < ? ORDER BY Fiscal_Week DESC",
            (forecast_name, fiscal_week))
        cols = [d[0] for d in cur.description]
        history_rows = [dict(zip(cols, (conv(v) for v in row))) for row in cur.fetchall()][::-1]  # chronological

        cur.execute(
            f"SELECT TOP {int(peers_cap)} * FROM {table} "
            f"WHERE Fiscal_Week = ? AND Region = ? AND SubRegion = ? AND Country = ? AND channel = ? "
            f"AND Forecast_name <> ?",
            (fiscal_week, region, subregion, country, channel, forecast_name))
        cols = [d[0] for d in cur.description]
        peer_rows = [dict(zip(cols, (conv(v) for v in row))) for row in cur.fetchall()]

        return {
            "target_row": target_rows[0] if target_rows else None,
            "history_rows": history_rows,
            "peer_rows": peer_rows,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        conn.close()


# Curated model picker list — only models verified reachable on the current NVIDIA/Groq
# accounts and fast enough for an interactive request. Override in config.json via
# "llm".selectable_models (same {provider, model, label, default?} shape) if the catalog
# changes. /api/models filters this to providers that actually have a key configured.
DEFAULT_SELECTABLE_MODELS = [
    {"provider": "nvidia", "model": "nvidia/nemotron-3-super-120b-a12b",
     "label": "Nemotron 3 Super 120B — fast, strong reasoning", "default": True},
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-flash",
     "label": "DeepSeek V4 Flash — reasoning"},
    {"provider": "nvidia", "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
     "label": "Nemotron Super 49B — reasoning, fast"},
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b",
     "label": "Nemotron 3 Ultra 550B — flagship (may be busy)"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile",
     "label": "Llama 3.3 70B (Groq) — fast baseline"},
]


@app.get("/api/models")
def models():
    """Models the console's per-queue picker can offer, filtered to providers that
    actually have an API key configured (so the UI never lists an unusable model)."""
    cfg = load_config()
    llm = cfg.get("llm", {})
    provider_has_key = set()
    for slot in llm.values():
        if isinstance(slot, dict) and slot.get("provider") and slot.get("api_key"):
            provider_has_key.add(slot["provider"])
    catalog = llm.get("selectable_models") or DEFAULT_SELECTABLE_MODELS
    available = [m for m in catalog if m.get("provider") in provider_has_key]
    return {"models": available, "providers_configured": sorted(provider_has_key)}


@app.get("/api/cqn-mapping")
def cqn_mapping(table: str = Query("dbo.CQN_Mapping", description="Mapping table to read")):
    """The authoritative Forecast_Name -> Combined_Queue_Name mapping, from SQL.

    Loaded by backend/upload_cqn_mapping.py from the client's mapping workbook. The console
    calls this after connecting to SQL so the "unmapped" badge reflects the real mapping
    instead of requiring a manual file upload.

    A Forecast_Name can belong to MORE THAN ONE Combined Queue (vendor-site splits such as
    Concentrix vs CGS): `mapping` gives the first for display, `all_queues` gives every one.
    Returns configured:false rather than an error when the table has not been loaded yet, so
    the console can degrade quietly.
    """
    cfg = load_config()
    if not cfg.get("sql", {}).get("server"):
        return {"configured": False, "reason": "SQL not configured.", "mapping": {}, "count": 0}
    conn = None
    try:
        conn = connect(cfg)
        cur = conn.cursor()
        cur.execute(f"SELECT Forecast_Name, Combined_Queue_Name FROM {table} "
                    f"WHERE Forecast_Name IS NOT NULL AND Combined_Queue_Name IS NOT NULL")
        first, every = {}, {}
        for name, cqn in cur.fetchall():
            name, cqn = str(name).strip(), str(cqn).strip()
            first.setdefault(name, cqn)
            every.setdefault(name, [])
            if cqn not in every[name]:
                every[name].append(cqn)
        return {"configured": True, "table": table, "mapping": first, "all_queues": every,
                "count": len(first),
                "multi_queue_names": sorted(k for k, v in every.items() if len(v) > 1)}
    except Exception as e:
        # Not loaded / unreachable is a normal state, not a 500 — the console falls back.
        return {"configured": False, "reason": str(e)[:200], "mapping": {}, "count": 0}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ------------------------------------------------------------------------------------------------
# The third LLM call. Kept OUT of the investigation pipeline on purpose: it is the only call whose
# output nothing else depends on, so it is also the only one safe to make optional.
_SUMMARY_CACHE = {}
_SUMMARY_CACHE_MAX = 200


@app.post("/api/rca-summarise")
def rca_summarise(payload: dict,
                  provider: str = Query("", description="Optional model-picker provider"),
                  model: str = Query("", description="Optional model-picker model id"),
                  refresh: int = Query(0, description="1 = ignore the cache and call again")):
    """Summarise a finished investigation into a few sentences.

    Body is the investigation RESULT the console already holds, so this re-uses work rather than
    re-running anything: no SQL, no second investigation, one provider call.

    Deterministic fields only go to the model -- not the narrative from call 1 or the interrogation
    prose from call 2. Summarising another model's prose would let a first-call error come back as an
    established fact in the part a lead is most likely to forward on.
    """
    from wfm import summary_prompt
    from wfm.spec_engine import _call_llm   # already returns (parsed, error)

    result = payload.get("result") or payload
    q = result.get("queue") or {}
    # The data token is PART OF THE KEY, not metadata beside it. Without it this cache is a
    # correctness bug on a table that is reloaded on a cadence: a queue-week whose actuals are
    # later restated keeps the same Forecast_name and Fiscal_Week, so the old summary -- written
    # from figures that no longer exist -- would be served as though it were current. The token
    # comes from the investigation response the console is holding; when it is absent the key
    # falls back to today's behaviour rather than refusing to cache.
    token = (payload.get("data_token")
             or ((result.get("data_freshness") or {}).get("token"))
             or "no-token")
    key = "%s|%s|%s|%s" % (q.get("Forecast_name") or "?", q.get("Fiscal_Week") or "?",
                           summary_prompt.SUMMARY_PROMPT_VERSION, token)

    if not refresh and key in _SUMMARY_CACHE:
        cached = dict(_SUMMARY_CACHE[key])
        cached["cached"] = True
        return cached

    if not (result.get("forecast_summary") or result.get("root_cause")):
        return {"ok": False, "error": "no investigation result supplied to summarise",
                "summary": None}

    llm_cfg = (load_config() or {}).get("llm") or {}
    choice = {"provider": provider, "model": model} if model else None
    messages = summary_prompt.build_summary_messages(result)

    parsed, err = _call_llm(messages, llm_cfg, choice, prefer_fast=True)
    if err or not parsed:
        return {"ok": False, "error": str(err or "no response from the model"), "summary": None,
                "note": ("The investigation itself is unaffected -- every figure and finding on the "
                         "card is deterministic and already complete. Only this summary is missing.")}

    ok, errors = summary_prompt.validate_summary(parsed, result)
    if not ok:
        # Same posture as the narrative: a summary that fails grounding is discarded, not shown with
        # a warning. A wrong number in the shortest, most-forwarded paragraph is the worst place for it.
        return {"ok": False, "error": "; ".join(errors), "summary": None,
                "note": ("The model's summary was rejected because it did not survive the numeric "
                         "grounding check. The card's own figures are unaffected.")}

    out = {"ok": True, "cached": False,
           "summary": parsed.get("summary"), "headline": parsed.get("headline"),
           "watch_next": parsed.get("watch_next"),
           "prompt_version": summary_prompt.SUMMARY_PROMPT_VERSION}
    if len(_SUMMARY_CACHE) >= _SUMMARY_CACHE_MAX:
        _SUMMARY_CACHE.pop(next(iter(_SUMMARY_CACHE)))
    _SUMMARY_CACHE[key] = out
    return out


@app.post("/api/rca-investigate")
def rca_investigate(context_bundle: dict, provider: str = Query("", description="Optional model-picker provider"),
                    model: str = Query("", description="Optional model-picker model id"),
                    mode: str = Query("wfm", description="'wfm' (default) = WFM cross-functional engine; 'spec' = FC_RCA v2.0.0 canonical 15-step engine; 'legacy' = original engine"),
                    grain: str = Query("weekly", description="spec mode only: weekly | monthly | quarterly"),
                    interrogate: int = Query(1, description="spec mode only: 1 = run the WHY interrogation (2 extra LLM calls), 0 = skip")):
    """
    LLM Investigation Engine proxy. Body = the generic ContextBundle the console
    builds client-side (target row + history + peers + auto-discovered statistical
    summary). Optional ?provider=&model= route the investigation to a specific model
    the user picked for this queue (used to compare which model gives business-acceptable
    output); if that model fails, the engine returns the deterministic best-supported
    finding — it does NOT silently answer with a different model.

    ?mode=wfm (default) selects the WFM cross-functional engine (backend/rca_wfm.py): the
    business-authored prompt, a top-5 ranked RCA list, skeptic review, hypothesis
    marking, the investigation ladder (is the miss inherited from a higher level?),
    104-week temporal context and channel-migration detection. It is ADDITIVE — with
    mode=legacy this endpoint behaves as the original engine. The WFM engine fills the original response keys too
    (primary_root_cause / secondary_contributors / key_findings), so the existing UI
    renders it without modification.

    Runs server-side ONLY so a real provider key never has to live in the
    (publicly hosted) rca_console.html.
    """
    cfg = load_config()
    model_choice = {"provider": provider, "model": model} if model else None

    if (mode or "wfm").lower() != "legacy":

        # The deeper context (104 weeks, channel siblings, higher-level rollups) is
        # fetched here rather than in the browser, so no frontend change is needed.
        # If SQL is unreachable the engine still runs on the posted bundle alone.
        target = (context_bundle or {}).get("target") or {}
        fields = target.get("fields") or {}
        key = {
            "Forecast_name": (target.get("key") or {}).get("Forecast_name") or fields.get("Forecast_name"),
            "Fiscal_Week": (target.get("key") or {}).get("Fiscal_Week") or fields.get("Fiscal_Week"),
            "Region": fields.get("Region"), "SubRegion": fields.get("SubRegion"),
            "Country": fields.get("Country"), "channel": fields.get("channel"),
            "business_org": fields.get("business_org"),
            # Offering is a rung of the investigation ladder (Country -> Offering -> Channel),
            # so it has to travel with the key or that level is silently skipped.
            "Offering": fields.get("Offering"),
        }
        wfm_context = {}
        # CONNECT FAILURE AND FETCH FAILURE ARE NOT THE SAME THING, and conflating them is how a
        # dropped VPN used to produce a confident-looking RCA built on 13 weeks of posted rows.
        #
        #   cannot CONNECT  -> the analysis would be running on a fraction of the evidence and
        #                      the user can fix it in ten seconds. Refuse, and say how. 503.
        #   connected, but the FETCH failed -> a schema or permission problem the user cannot
        #                      fix from the console. Degrade, and state what is missing.
        conn = _sql_or_503(cfg)
        try:
            cur = conn.cursor()
            wfm_context = fetch_wfm_context(cur, cfg.get("sql", {}).get("table", "dbo.Input_To_ML"), key)
            # Stamp the load this investigation was built from, so a card can later be shown to
            # predate a refresh instead of quietly disagreeing with the current table.
            try:
                wfm_context["data_freshness"] = _freshness(cur, cfg)
            except Exception as e:                      # never fail an investigation over this
                wfm_context["data_freshness"] = {"available": False, "error": str(e)}
        except Exception as e:
            wfm_context = {"fetch_error": str(e)}
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        # ?mode=spec runs the FC_RCA v2.0.0 canonical 15-step workflow. It is deliberately a
        # SEPARATE engine rather than a rewrite of the WFM one: the same queue can be
        # investigated both ways and the outputs compared, and rollback is a query parameter
        # rather than a revert.
        # The load this card was built from, stamped on the RESPONSE rather than left inside
        # wfm_context. The engines copy forward the context keys they know about, so a new key
        # placed there simply never surfaced -- verified against a live run before this was
        # moved. Stamping here also keeps both engines consistent without either knowing about
        # freshness, which is not their concern.
        def _stamp(result):
            fresh = (wfm_context or {}).get("data_freshness")
            if isinstance(result, dict) and fresh:
                result.setdefault("data_freshness", fresh)
            return result

        if (mode or "").lower() == "spec":
            try:
                return _stamp(investigate_spec(context_bundle, cfg.get("llm", {}), wfm_context,
                                               grain=grain, model_choice=model_choice,
                                               interrogate=bool(interrogate)))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Spec investigation failed: {e}")
        try:
            return _stamp(investigate_wfm(context_bundle, cfg.get("llm", {}), wfm_context,
                                          model_choice=model_choice))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"WFM investigation failed: {e}")

    try:
        return investigate(context_bundle, cfg.get("llm", {}), model_choice=model_choice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {e}")


# Serve the static UI from the repo root. Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
