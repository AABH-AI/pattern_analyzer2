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
- **Windows (easiest):** `run.bat` — also checks/starts the VPN, verifies the SQL host is
  reachable, and can run the test suites (`--smoke` / `--validate` / `--llm` / `--all`).
- **Windows (PowerShell):** `powershell -ExecutionPolicy Bypass -File run.ps1`
- **Linux/macOS:** `chmod +x run.sh && ./run.sh`
- **Docker (any OS, bundles the ODBC driver):** put creds in `.env` (see `backend/.env.example`), then
  `docker compose up -d --build`. Full details in `DEPLOY.md`.

The runner installs deps, creates `backend/config.json` from the example (you fill in the SQL details),
then starts the server at **http://localhost:9400/rca_console.html**.

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
- `POST /api/rca-investigate[?provider=&model=]` → the RCA report (see `IMP_DOCS/rca-investigation-contract.md`)
- `POST /api/rca-investigate?mode=wfm` → the **WFM business-prompt engine** (branch `wfm-rca`):
  top-5 ranked causes, skeptic review, hypothesis marking, investigation ladder, 104-week
  temporal context, channel-migration detection, and the ±10% "don't investigate in-band" rule.
  **Additive** — omit `mode` and the endpoint behaves exactly as before. It also backfills every
  legacy response key, so the existing UI renders it unchanged.
  Full contract + known gaps: `IMP_DOCS/wfm-rca-engine.md`.

## If you are an AI agent, do this
1. Detect the OS; run `run.bat` (Windows, preferred — it also handles the VPN and can run the test suites), `run.ps1` (Windows/PowerShell) or `run.sh` (POSIX). If Docker is available and preferred, use `docker compose up -d --build`.
2. If `backend/config.json` is missing, create it from `backend/config.example.json` and ask the user for the SQL login (never guess credentials).
3. If there is no SQL access / not on the network, fall back to the **file-upload** path and say so.
4. Verify with `GET /api/health` (expect `configured:true`) and `GET /api/data?limit=1`.
5. **Do not fabricate** queue names, numbers, or schema — everything is derived from the loaded data.
6. For an RCA investigation, pick an **NVIDIA** model — Groq is faster but has a 100,000 token/**day**
   cap, and once it is spent every call 429s and the engine returns its deterministic finding
   (honest, but not the LLM). An NVIDIA investigation takes **45–100s**; that is not a hang.
7. Before claiming the engine works, run the suites in `results/`:
   `python results/smoke_test_modules.py` (12 modules), `run_validation.py` (SQL cross-checks),
   `run_llm_ranking.py` (asserts the LLM actually answered).

## Repo map
```
rca_console.html                     the app (console, dashboard, timeline, definitions)
rca_timeline.html                    standalone build Gantt (auto-dates to the PC clock)
index.html                           landing/entry
run.bat                              Windows one-shot: deps, config, VPN, SQL check, backend,
                                     optional --smoke/--validate/--llm suites, browser
run.ps1 / run.sh                     same idea for PowerShell / POSIX
docker-compose.yml                   always-on hosting (see DEPLOY.md)
DEPLOY.md                            internal-server deployment (Docker / Windows service / systemd)
backend/                             FastAPI + pyODBC connector + Excel→SQL loader
  sql_backend.py                     the API; ?mode=wfm branch selects the WFM engine
  rca_investigate.py                 the ORIGINAL RCA engine (default path)
  rca_wfm.py                         compatibility shim -> the wfm/ package
  wfm/                               the WFM engine, one module per responsibility:
    investigation_engine.py            orchestration + the ±10% in-band gate
    hierarchy_analyzer.py              Business Org → Region → … drill-down / inherited_from
    channel_migration_detector.py      Voice ↔ Chat ↔ Email shifts in one locality
    temporal_reasoner.py               104 weeks, prior/4/13 wk, same week last year
    correlation_engine.py              driver relationships + the exact ASU decomposition
    skeptic.py                         REJECTS causes the features cannot support
    hypothesis_generator.py            "Hypothesis – To be Validated" marking
    business_report_generator.py       executive report + legacy-key back-compat
    data_quality.py                    is the number itself credible?
    data_access.py, prompts.py, llm_client.py, common.py
  upload_excel_to_sql.py, requirements.txt,
  config.example.json (copy → config.json), .env.example, Dockerfile, README.md
results/                             validation evidence + re-runnable test scripts
  audit-log.md                       START HERE — the full audit trail
  run_validation.py                  SQL cross-check suite (5 queues × 8 checks)
  run_llm_ranking.py                 LLM ranking verification (asserts the LLM really ran)
  smoke_test_modules.py              per-module smoke test (12 modules)
  canary-v0.2/, canary-v0.3-llm/     recorded browser sessions (report.html + screenshots)
IMP_DOCS/                            installation-and-connection.md, design-choice.md, handoff.md,
                                     TODO.md, prompt-trail.md, wfm-rca-engine.md, canary-test-log.md
```

## Guardrails
- Keep `rca_console.html` **library-free** (must run offline / behind Kong).
- Never change the two formulas' math — only display/rounding; the ⓘ modal must match what's computed.
- `config.json` and `.env` are **secret** (gitignored) — never commit or print credentials.
- The public/static host (e.g. GitHub Pages) can run the UI + file upload but **cannot** use live SQL
  (no backend, and the DB is internal) — by design.
