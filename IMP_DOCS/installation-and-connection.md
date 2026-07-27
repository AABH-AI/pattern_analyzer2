# Installation & SQL Connection Guide

How to run the RCA Console and connect it to SQL Server. Two ways to run it:
**(A) file-only** (no backend, upload the file by hand) and **(B) with the backend**
(live "Connect to SQL Server (AA)"). The backend is what makes the SQL button work.

---

## 0. What connects to what
```
Browser (rca_console.html)
   └── fetch /api/data ──► FastAPI backend (backend/sql_backend.py)
                                └── pyODBC ──► SQL Server 10.10.9.75 / Playground / dbo.Input_To_ML
```
The browser **cannot** reach SQL Server directly — the backend does the query and returns JSON.

---

## A. File-only (no install, quickest)
1. Open `rca_console.html` in Chrome/Edge (double-click, or serve behind Kong).
2. **RCA Console → Upload weekly file** → pick `Input_To_ML_*.xlsx/.csv`.
3. (Optional) **Upload CQN mapping** to resolve Combined Queue Names.

No SQL, no backend. The **Connect to SQL Server** button will not work in this mode.

---

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
uvicorn sql_backend:app --port 8000
```
Open **http://localhost:8000/rca_console.html** → **🗄 Connect to SQL Server (AA) → Fetch table**.

`config.json` example (this is **gitignored** — never committed):
```json
{
  "sql": {
    "server": "10.10.9.75",
    "database": "Playground",
    "table": "dbo.Input_To_ML",
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
python upload_excel_to_sql.py               # create + load all 138,775 rows
```

---

## C. Always-on server (Docker) — for shared/team use
See **`DEPLOY.md`** in the repo root. Short version, on a server inside the AA network:
```bash
copy backend\.env.example .env      # put SQL_USERNAME / SQL_PASSWORD in .env
docker compose up -d --build
```
Then anyone on the AA network opens **`http://<server-ip>:8000/rca_console.html`**.
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

Quick self-check: open `http://<host>:8000/api/health`.
`configured:true` = config is loaded; then `http://<host>:8000/api/data?limit=1` should return one row.

---

## Security notes
- `config.json` and `.env` are **gitignored** — credentials never leave the machine/repo.
- The backend binds `0.0.0.0` for shared use; keep it on the internal network (not public internet).
- The public UI link is a demo (file-upload only); live SQL stays inside the AA network.
