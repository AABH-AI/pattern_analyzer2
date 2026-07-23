# -*- coding: utf-8 -*-
"""
Local backend for the Demand Pattern RCA Agent.

- GET /api/health  -> {status, configured, table}
- GET /api/data    -> {columns, rows, count}   (runs SELECT * FROM <table>)
- everything else  -> serves the static UI from the repo root, so opening
  http://localhost:8000/rca_prototype.html and clicking "Connect to SQL Server"
  is a same-origin fetch.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn sql_backend:app --port 8000
Then open http://localhost:8000/rca_prototype.html  (or open the file directly;
CORS is open so the file:// page can still reach http://localhost:8000).

Connection details come from backend/config.json (see config.example.json).
config.json is gitignored so credentials are never committed.
"""
import json
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent               # repo root, where the .html files live
CONFIG = HERE / "config.json"

app = FastAPI(title="Demand Pattern RCA - SQL connector")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def load_config():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {}


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


# Serve the static UI from the repo root. Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
