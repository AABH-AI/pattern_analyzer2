# Backend — SQL Server connector

Gives the prototype a **live "Connect to SQL Server"** path (the browser can't reach
SQL Server directly, so this small FastAPI service does the query and hands rows to the UI).
The existing **file-upload** path in `rca_prototype.html` still works with no backend.

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
Open **http://localhost:8000/rca_prototype.html** → click **🗄 Connect to SQL Server**.
(You can also open the .html file directly; CORS is open so it still reaches localhost:8000.)

## Endpoints
- `GET /api/health` → `{status, configured, table}`
- `GET /api/data?limit=N` → `{columns, rows, count}` (SELECT * FROM &lt;table&gt;; `limit` optional)
