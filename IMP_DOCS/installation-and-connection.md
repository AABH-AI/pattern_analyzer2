# Installation & SQL Connection Guide

How to run the RCA Console and connect it to SQL Server. Two ways to run it:
**(A) file-only** (no backend, upload the file by hand) and **(B) with the backend**
(live "Connect to SQL Server (AA)"). The backend is what makes the SQL button work.

---

## 0. What connects to what
```
Browser (rca_console.html)
   └── fetch /api/data ──► FastAPI backend (backend/sql_backend.py)
                                └── pyODBC ──► SQL Server 10.10.9.75 / Playground / dbo.Input_To_ML_Full_138_Trimmed
```
The browser **cannot** reach SQL Server directly — the backend does the query and returns JSON.

---

## A. File-only (no install, quickest)
1. Open `rca_console.html` in Chrome/Edge (double-click, or serve behind Kong).
2. **RCA Console → Upload weekly file** → pick `Input_To_ML_*.xlsx/.csv`.
3. (Optional) **Upload CQN mapping** to resolve Combined Queue Names.

No SQL, no backend. The **Connect to SQL Server** button will not work in this mode.

---

## A2. One command on Windows — `run.bat`

```bat
run.bat                 :: deps, config, VPN, SQL reachability, backend, browser
run.bat --all           :: ...and run all three test suites
run.bat --smoke         :: 12-module smoke test only (no SQL, no LLM needed)
run.bat --tests-only    :: run suites against an already-running backend
run.bat --no-vpn        :: skip the VPN step
```

Nine stages, and it stops with a clear message if one fails. The VPN stage detects **Cisco Secure
Client**, checks `vpncli status`, tries `connect aavpn.alignedautomation.com`, and if the CLI
cannot finish (SAML/MFA logins can't be done from a command line) it launches the desktop app and
polls up to 90s for the tunnel. The SQL host is read from `config.json`, not hardcoded.

## B. With the backend (live SQL) — local

### Prerequisites
- **Python 3.11+**
- **Microsoft ODBC Driver 17 or 18 for SQL Server** installed on the machine
- Network line-of-sight to `10.10.9.75` (be on the **AA network / VPN**)
- A **SQL Server login** with read access to `Playground`

### Steps
```bash
cd backend
pip install -r requirements.txt
copy config.example.json config.json          # Windows  (cp on Linux/mac)
# edit config.json → server, database, table, auth=sql, username, password, driver
uvicorn sql_backend:app --port 9400
```
Open **http://localhost:9400/rca_console.html** → **🗄 Connect to SQL Server (AA) → Fetch table**.

`config.json` example (this is **gitignored** — never committed):
```json
{
  "sql": {
    "server": "10.10.9.75",
    "database": "Playground",
    "table": "dbo.Input_To_ML_Full_138_Trimmed",
    "auth": "sql",
    "username": "YOUR_LOGIN",
    "password": "YOUR_PASSWORD",
    "driver": "ODBC Driver 17 for SQL Server",
    "encrypt": false,
    "trust_server_certificate": true
  }
}
```

### Load the data into SQL (one time, if the table isn't there yet)
```bash
python upload_excel_to_sql.py --dry-run     # verify parsing, touches no DB
python upload_excel_to_sql.py --schema-only # create the table only
python upload_excel_to_sql.py               # create + load the full extract
#   The LIVE table on this branch is dbo.Input_To_ML_Full_138_Trimmed: 114,436 rows, 32 columns.
#   dbo.Input_To_ML (66,612) and dbo.Input_To_ML_Full (88,816) are earlier loads and
#   are NOT what the engine reads -- check backend/config.json before assuming.
```

---

## C. Always-on server (Docker) — for shared/team use
See **`DEPLOY.md`** in the repo root. Short version, on a server inside the AA network:
```bash
copy backend\.env.example .env      # put SQL_USERNAME / SQL_PASSWORD in .env
docker compose up -d --build
```
Then anyone on the AA network opens **`http://<server-ip>:9400/rca_console.html`**.
`restart: unless-stopped` keeps it running across reboots — no laptop required.

---

## Connection endpoints (backend)
| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{status, configured, table}` — quick "is SQL wired?" check |
| `GET /api/data` | `{columns, rows, count}` — `SELECT * FROM <table>` |
| `GET /api/data?limit=100` | first 100 rows (handy for testing) |

---

## Troubleshooting — "I pulled the repo but SQL doesn't connect"
A `git pull` copies **code only**. It does **not** carry the connection or the network. Check in order:

1. **No `config.json`.** It's gitignored, so it isn't in the repo. Create it from `config.example.json` (or set `SQL_*` env vars). Symptom: `/api/data` → **503 "SQL not configured"**.
2. **Not on the AA network / VPN.** `10.10.9.75` is a private IP; off-network machines can't route to it. Symptom: **connection timeout**.
3. **Backend not running.** Pulling files ≠ starting the service. Run `uvicorn …` or `docker compose up -d`. Symptom: button error / fetch fails.
4. **Login/permission.** Wrong SQL login or no rights to `Playground`. Symptom: **"Login failed for user …" (18456)**.
5. **ODBC driver missing** (non-Docker). Install ODBC Driver 17/18. Symptom: **driver/data-source error**. (Docker bundles it.)
6. **Opened the public GitHub Pages page.** That's static — it has no backend, so the SQL button can't work there **by design**. Use the backend URL instead.

Quick self-check: open `http://<host>:9400/api/health`.
`configured:true` = config is loaded; then `http://<host>:9400/api/data?limit=1` should return one row.

---

## LLM configuration (RCA investigation)

`backend/config.json` → `llm`:

| Key | Meaning |
|---|---|
| `primary` / `secondary` | provider slots (`nvidia`, `groq`) with `api_key` and optional `model` |
| `timeout_seconds` | LLM read timeout for **both** engines. Omit for the original 100s; currently **150** |
| `selectable_models` | what the console's per-queue model picker offers |

Practical notes, measured:

- **NVIDIA** reasoning models take **45–100s** per investigation, and roughly **1 call in 3 hangs**.
  A larger timeout does not fix that — 300s was measured as *worse* than 150s (same success rate,
  failures simply took five minutes).
- **Groq** answers in 2–6s but has a **100,000 token/day** cap. Once spent, every call returns
  HTTP 429 and the engine falls back to its deterministic finding — honest, but not the LLM. The
  reason is always recorded in the response's `missing_information`.
- Leave both `api_key` fields blank to get the deterministic feature-based finding only. The engine
  never fabricates a conclusion.

## Which RCA engine am I calling?

Two engines sit behind one endpoint:

| Call | Engine |
|---|---|
| `POST /api/rca-investigate` | the original single-call investigation (what the console uses today) |
| `POST /api/rca-investigate?mode=wfm` | the WFM engine — ranked causes, skeptic review, investigation ladder, 104-week context, channel migration, and the ±10% in-band rule |

`?mode=wfm` is additive: omit it and nothing changes. It also backfills the legacy response keys,
so the existing console renders its output unmodified. Contract and known gaps:
`wfm-rca-engine.md`.

**To verify an install actually works**, run the suites in `results/` (they are re-runnable and
re-derive every number from SQL independently):

```bash
cd backend
python ../results/smoke_test_modules.py   # 12 modules, no SQL or LLM needed
python ../results/run_validation.py       # 5 queues x 8 SQL cross-checks
python ../results/run_llm_ranking.py      # 3 queues; fails if the LLM did not answer
```

Start with `results/audit-log.md` for what has already been verified.

## Security notes
- `config.json` and `.env` are **gitignored** — credentials never leave the machine/repo.
- The backend binds `0.0.0.0` for shared use; keep it on the internal network (not public internet).
- The public UI link is a demo (file-upload only); live SQL stays inside the AA network.
