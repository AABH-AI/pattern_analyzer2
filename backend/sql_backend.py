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
  http://localhost:8000/rca_console.html and clicking "Investigate Root Cause"
  is a same-origin fetch.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn sql_backend:app --port 8000
Then open http://localhost:8000/rca_console.html  (or open the file directly;
CORS is open so the file:// page can still reach http://localhost:8000).

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
from rca_verify import claims_from_response, verify as verify_claims
from wfm import fetch_wfm_context, investigate_wfm

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
    return pyodbc.connect(conn_str, timeout=int(c.get("timeout", 30)))


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


def _attach_cqn(context_bundle, cfg):
    """Put the Combined Queue identity into context_bundle["meta"]["cqn"].

    A Forecast_Name can belong to more than one Combined Queue (69 of 442 do -- vendor-site
    splits), so all of them are carried and `primary` is the one used for display.
    `members_this_week` lists the queue+channel rows that actually reported in the target week,
    which is what makes it possible to say "3 of the 7 queues in <CQN>" instead of
    "3 of 5 similar queues".
    """
    target = (context_bundle or {}).get("target") or {}
    fields = target.get("fields") or {}
    name = (target.get("key") or {}).get("Forecast_name") or fields.get("Forecast_name")
    week = (target.get("key") or {}).get("Fiscal_Week") or fields.get("Fiscal_Week")
    if not name:
        return
    table = cfg.get("sql", {}).get("table", "dbo.Input_To_ML")
    conn = connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT Combined_Queue_Name FROM dbo.CQN_Mapping "
                    "WHERE Forecast_Name = ? AND Combined_Queue_Name IS NOT NULL", (name,))
        names = [r[0] for r in cur.fetchall()]
        if not names:
            return
        members = []
        if week is not None:
            marks = ", ".join("?" for _ in names)
            cur.execute(
                f"SELECT d.Forecast_name, d.channel, d.Actual_Offered, d.fcst_offered "
                f"FROM {table} d WHERE d.Fiscal_Week = ? AND EXISTS ("
                f"  SELECT 1 FROM dbo.CQN_Mapping m WHERE m.Forecast_Name = d.Forecast_name "
                f"    AND m.Combined_Queue_Name IN ({marks}))",
                tuple([week] + names))
            for fn, ch, ao, fo in cur.fetchall():
                members.append({"Forecast_name": fn, "channel": ch,
                                "Actual_Offered": ao, "fcst_offered": fo})
        meta = context_bundle.setdefault("meta", {})
        meta["cqn"] = {
            "primary": names[0],
            "all": names,
            "is_multi_queue": len(names) > 1,
            "members_this_week": members,
            "channels_in_cqn": sorted({str(m["channel"]) for m in members if m.get("channel")}),
            "source": "dbo.CQN_Mapping",
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


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


@app.post("/api/rca-investigate")
def rca_investigate(context_bundle: dict, provider: str = Query("", description="Optional model-picker provider"),
                    model: str = Query("", description="Optional model-picker model id"),
                    mode: str = Query("", description="'wfm' for the WFM cross-functional engine; "
                                                      "empty (default) = the original engine, unchanged")):
    """
    LLM Investigation Engine proxy. Body = the generic ContextBundle the console
    builds client-side (target row + history + peers + auto-discovered statistical
    summary). Optional ?provider=&model= route the investigation to a specific model
    the user picked for this queue (used to compare which model gives business-acceptable
    output); if that model fails, the engine returns the deterministic best-supported
    finding — it does NOT silently answer with a different model.

    ?mode=wfm selects the WFM cross-functional engine (backend/rca_wfm.py): the
    business-authored prompt, a top-5 ranked RCA list, skeptic review, hypothesis
    marking, the investigation ladder (is the miss inherited from a higher level?),
    104-week temporal context and channel-migration detection. It is ADDITIVE — with
    no mode= parameter this endpoint behaves exactly as it always has, so the console
    needs no change. The WFM engine fills the original response keys too
    (primary_root_cause / secondary_contributors / key_findings), so the existing UI
    renders it without modification.

    Runs server-side ONLY so a real provider key never has to live in the
    (publicly hosted) rca_console.html.
    """
    cfg = load_config()
    model_choice = {"provider": provider, "model": model} if model else None

    # Resolve the authoritative Combined Queue for this queue and attach it to the bundle, for
    # BOTH engines. Without this the default engine has no CQN name at all and can only say
    # "similar queues (same region, country and channel)" -- which is a locality group, not the
    # Combined Queue. Silent no-op if dbo.CQN_Mapping is not loaded.
    try:
        _attach_cqn(context_bundle, cfg)
    except Exception:
        pass

    if (mode or "").lower() == "wfm":
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
        }
        wfm_context = {}
        conn = None
        try:
            conn = connect(cfg)
            wfm_context = fetch_wfm_context(conn.cursor(), cfg.get("sql", {}).get("table", "dbo.Input_To_ML"), key)
        except Exception as e:
            # Not fatal: the WFM engine degrades to the posted bundle and says what is missing.
            wfm_context = {"fetch_error": str(e)}
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        try:
            return investigate_wfm(context_bundle, cfg.get("llm", {}), wfm_context, model_choice=model_choice)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"WFM investigation failed: {e}")

    try:
        return investigate(context_bundle, cfg.get("llm", {}), model_choice=model_choice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {e}")



@app.post("/api/verify-finding")
def verify_finding(payload: dict,
                   history_cap: int = Query(13, ge=2, le=104,
                                            description="Weeks used for 'usual' -- match the engine")):
    """Re-derive an RCA's quoted numbers from SQL and return the query that did it.

    Body is either a whole investigation response (the console can post back exactly what it
    rendered) or `{"queue": {...}, "claims": [...]}`. No LLM is involved: the verifier has to be
    independent of the thing it verifies, or it proves nothing.

    Returns per-claim `verified` / `mismatch` / `unsupported` / `no_data`, each with the SQL, so a
    reader can paste it into their own client. `reproducible_share` is the fraction of quoted
    numbers that reproduce -- deliberately not called "confidence", because unlike the model's
    self-reported score it is a fact.
    """
    cfg = load_config()
    if not cfg.get("sql", {}).get("server"):
        raise HTTPException(status_code=503, detail="SQL not configured.")
    table = cfg.get("sql", {}).get("table", "dbo.Input_To_ML")

    queue = payload.get("queue") or {}
    if not queue:
        target = (payload.get("target") or {})
        key = target.get("key") or {}
        fields = target.get("fields") or {}
        queue = {"Forecast_name": key.get("Forecast_name") or fields.get("Forecast_name"),
                 "Fiscal_Week": key.get("Fiscal_Week") or fields.get("Fiscal_Week")}
    if not queue.get("Forecast_name") or queue.get("Fiscal_Week") in (None, ""):
        raise HTTPException(status_code=400,
                            detail="Need queue.Forecast_name and queue.Fiscal_Week (or a full "
                                   "investigation response containing target.key).")
    claims = payload.get("claims")
    if claims is None:
        claims = claims_from_response(payload)

    conn = connect(cfg)
    try:
        return verify_claims(conn.cursor(), table, queue, claims, history_cap=history_cap)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Serve the static UI from the repo root. Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
