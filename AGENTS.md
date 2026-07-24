# AGENTS.md — how to run this application (for Claude / any AI, and humans)

If you are an AI assistant (Claude Code, etc.) opening this repo, **read this file first**, then
`IMP_DOCS/installation-and-connection.md` and `DEPLOY.md`. This tells you exactly what the app is,
what it needs, and how to run it. **Do not invent data, columns, servers, or credentials** — use only
what is in the files / config; if something is missing, ask or state the assumption.

## What this is
**Demand Pattern RCA Agent — Console.** A single self-contained HTML app that reads weekly
support-demand data, computes two rule-based metrics, flags forecast misses, and shows a per-queue
root-cause report + a volumetrics dashboard.
- **Front end:** `rca_console.html` — one file, **no libraries / no CDN / no build step** (XLSX+CSV
  parser, filters, charts all hand-rolled). Runs from `file://` or served.
- **Back end (optional, for live SQL):** `backend/` — **FastAPI + pyODBC**. Serves the UI and a
  `/api/data` endpoint that runs `SELECT * FROM <table>` against SQL Server.

## The two metrics (never change the math; only display)
- **Forecast Accuracy** = `Actual_Offered / fcst_offered * 100`
- **Forecast Adherence** = `(1 − Actual_Offered / fcst_offered) * 100` — **signed** (− = actual above
  forecast / under-forecast; + = actual below / over-forecast). Flag when `|Forecast Adherence| > band` (default ±10%).
Rows with no/zero forecast are data gaps — never scored.

## Two ways to run

### A) File-only (no install) — always works
Open `rca_console.html` in Chrome/Edge → **Upload weekly file** (`.csv`/`.xlsx`). No SQL, no backend.
The "Connect to SQL Server" button will not work in this mode.

### B) With the backend (live SQL) — one command
Prereqs: **Python 3.11+**, **Microsoft ODBC Driver 17 or 18 for SQL Server**, network access to the
SQL Server, and a SQL login.
- **Windows:** `powershell -ExecutionPolicy Bypass -File run.ps1`
- **Linux/macOS:** `chmod +x run.sh && ./run.sh`
- **Docker (any OS, bundles the ODBC driver):** put creds in `.env` (see `backend/.env.example`), then
  `docker compose up -d --build`. Full details in `DEPLOY.md`.

The runner installs deps, creates `backend/config.json` from the example (you fill in the SQL details),
then starts the server at **http://localhost:8000/rca_console.html**.

## SQL setup (what the backend connects to)
Connection lives in `backend/config.json` (gitignored) or `SQL_*` env vars. Fields:
`server, database, table, auth ("sql"|"windows"), username, password, driver, encrypt, trust_server_certificate`.

**Data source used in this project:** SQL Server `10.10.9.75` → database **`Playground`** → table
**`dbo.Input_To_ML`** (**66,612 rows, 33 columns** — truncated to FY2025–2027). The loader keeps only
Fiscal_Week 202500–202799 via config `min_fiscal_week`/`max_fiscal_week` (or `--min-week`/`--max-week`);
remove them to load all years. Load it from the Excel with:
```
python backend/upload_excel_to_sql.py --dry-run    # verify parsing, no DB
python backend/upload_excel_to_sql.py              # create table + load all rows
```
Schema/data-types are documented in `IMP_DOCS/design-choice.md` (`Fiscal_Week` BIGINT, `Week_Ending`
DATE, dimensions NVARCHAR, measures FLOAT).

## Endpoints (backend)
- `GET /api/health` → `{status, configured, table}`
- `GET /api/data[?limit=N]` → `{columns, rows, count}`

## If you are an AI agent, do this
1. Detect the OS; run `run.ps1` (Windows) or `run.sh` (POSIX). If Docker is available and preferred, use `docker compose up -d --build`.
2. If `backend/config.json` is missing, create it from `backend/config.example.json` and ask the user for the SQL login (never guess credentials).
3. If there is no SQL access / not on the network, fall back to the **file-upload** path and say so.
4. Verify with `GET /api/health` (expect `configured:true`) and `GET /api/data?limit=1`.
5. **Do not fabricate** queue names, numbers, or schema — everything is derived from the loaded data.

## Repo map
```
rca_console.html                     the app (console, dashboard, timeline, definitions)
rca_timeline.html                    standalone build Gantt (auto-dates to the PC clock)
index.html                           landing/entry
run.ps1 / run.sh                     one-command setup + run
docker-compose.yml                   always-on hosting (see DEPLOY.md)
DEPLOY.md                            internal-server deployment (Docker / Windows service / systemd)
backend/                             FastAPI + pyODBC connector + Excel→SQL loader
  sql_backend.py, upload_excel_to_sql.py, requirements.txt,
  config.example.json (copy → config.json), .env.example, Dockerfile, README.md
IMP_DOCS/                            installation-and-connection.md, design-choice.md, handoff.md, TODO.md, prompt-trail.md
```

## Guardrails
- Keep `rca_console.html` **library-free** (must run offline / behind Kong).
- Never change the two formulas' math — only display/rounding; the ⓘ modal must match what's computed.
- `config.json` and `.env` are **secret** (gitignored) — never commit or print credentials.
- The public/static host (e.g. GitHub Pages) can run the UI + file upload but **cannot** use live SQL
  (no backend, and the DB is internal) — by design.
