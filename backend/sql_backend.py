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
                   country: str = "", channel: str = "", history_cap: int = 12, peers_cap: int = 15):
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


@app.post("/api/rca-investigate")
def rca_investigate(context_bundle: dict, provider: str = Query("", description="Optional model-picker provider"),
                    model: str = Query("", description="Optional model-picker model id")):
    """
    LLM Investigation Engine proxy. Body = the generic ContextBundle the console
    builds client-side (target row + history + peers + auto-discovered statistical
    summary). Optional ?provider=&model= route the investigation to a specific model
    the user picked for this queue (used to compare which model gives business-acceptable
    output); if that model fails, the engine returns the deterministic best-supported
    finding — it does NOT silently answer with a different model.

    Runs server-side ONLY so a real provider key never has to live in the
    (publicly hosted) rca_console.html.
    """
    cfg = load_config()
    model_choice = {"provider": provider, "model": model} if model else None
    try:
        return investigate(context_bundle, cfg.get("llm", {}), model_choice=model_choice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {e}")


# Serve the static UI from the repo root. Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
