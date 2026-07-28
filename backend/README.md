# Backend — SQL Server connector

Gives the prototype a **live "Connect to SQL Server"** path (the browser can't reach
SQL Server directly, so this small FastAPI service does the query and hands rows to the UI).
The existing **file-upload** path in `rca_console.html` still works with no backend.

> Quickest path on Windows: run **`..un.bat`** from the repo root instead of steps 1-4 — it
> installs deps, ensures `config.json`, brings up the VPN, checks the SQL host, starts this
> backend and opens the console. `run.bat --all` also runs the test suites in `../results/`.

## 1. Install
```bash
cd backend
pip install -r requirements.txt
```
You also need the Microsoft **ODBC Driver 17 (or 18) for SQL Server** installed on the machine.

## 2. Configure
```bash
copy config.example.json config.json        # Windows
```
Edit `config.json` with your server:
- `server` — e.g. `MYHOST\SQLEXPRESS` or `myhost,1433`
- `database`, `table` (default `dbo.Input_To_ML`)
- `auth` — `"windows"` (Trusted_Connection) or `"sql"` (then set `username`/`password`)
- `driver` — match what's installed (`ODBC Driver 17 for SQL Server` / `18`)

`config.json` is **gitignored** — credentials are never committed.

## 3. Load the Excel into SQL (one time)
```bash
python upload_excel_to_sql.py --dry-run     # verify parsing, no DB touched
python upload_excel_to_sql.py               # create table + bulk insert (~139k rows)
```

## 4. Run the connector
```bash
uvicorn sql_backend:app --port 8000
```
Open **http://localhost:8000/rca_console.html** → click **🗄 Connect to SQL Server**.
(You can also open the .html file directly; CORS is open so it still reaches localhost:8000.)

## Endpoints
- `GET /api/health` → `{status, configured, table}`
- `GET /api/data?limit=N` → `{columns, rows, count}` (SELECT * FROM &lt;table&gt;; `limit` optional)
- `GET /api/queue-context?forecast_name=...&fiscal_week=...&region=...&subregion=...&country=...&channel=...` →
  `{target_row, history_rows, peer_rows}`. Scoped fetch for RCA Investigation: queries SQL
  Server directly for **only** that one queue's own row, its prior-week history, and its
  same-week CQN peers — not the whole table. Used automatically when the console's data
  source is SQL (`window.SRC==='sql'`); file-upload mode has no SQL connection to query and
  filters the in-browser rows instead. If this query fails for any reason, the console falls
  back to in-browser filtering rather than failing the investigation outright.
- `POST /api/rca-investigate` → the LLM Investigation Engine proxy. Body is the generic
  `ContextBundle` the console builds client-side (target row + history + peers + an
  auto-discovered statistical summary — every field present in the source file, nothing
  hand-picked). Runs server-side so a real provider key never has to live in the
  (publicly hosted) `rca_console.html`.

  **Wired to NVIDIA (primary) + Groq (secondary fallback)**, both OpenAI-compatible chat
  APIs. With no key configured on either slot, this returns an honest placeholder — empty
  root-cause/hypotheses, not a fabricated one — and `missing_information` says so
  explicitly; the same happens if a live call fails (network/rate-limit/bad response),
  after trying primary then secondary. Priority is whatever `config.json`'s `llm.primary`/
  `llm.secondary` slots say — swap those two objects (or just the `provider` values) to
  reorder; env vars apply to whichever slot names that provider, not a fixed position.

  To go live: set `llm.primary.api_key` (NVIDIA) and/or `llm.secondary.api_key` (Groq) in
  `config.json` (or `GROQ_API_KEY`/`NVIDIA_API_KEY` env vars — see `.env.example` /
  `docker-compose.yml`). `model` is optional on both (sensible defaults are built in).
  No other code changes needed — see `rca_investigate.py`'s docstring and
  `IMP_DOCS/rca-investigation-contract.md` for the exact request/response shape, or to
  swap in a different provider later.

## WFM engine (opt-in)

`POST /api/rca-investigate?mode=wfm` selects the WFM cross-functional engine in `wfm/`
(13 modules: investigation_engine, hierarchy_analyzer, channel_migration_detector,
temporal_reasoner, correlation_engine, skeptic, hypothesis_generator,
business_report_generator, data_quality, data_access, prompts, llm_client, common).

Without `mode=` this endpoint behaves exactly as it always has. The WFM engine also backfills
every legacy response key, so the existing console renders its output unchanged.

`llm.timeout_seconds` in `config.json` sets the LLM read timeout for both engines (default 100
when the key is absent; currently 150 — NVIDIA reasoning models need 45–100s).

Contract, verification and known gaps: `../IMP_DOCS/wfm-rca-engine.md`.
Evidence and re-runnable test scripts: `../results/`.
