# CLAUDE.md

**Read `AGENTS.md` first** — it's the full runbook for running this app (UI + SQL backend).

Quick start:
- **Windows:** `powershell -ExecutionPolicy Bypass -File run.ps1`
- **Linux/macOS:** `./run.sh`
- **Docker:** `docker compose up -d --build` (see `DEPLOY.md`)
- **No install / no SQL:** open `rca_console.html` and use **Upload weekly file**.

Then open **http://localhost:8000/rca_console.html**.

Key facts:
- Front end is one self-contained file (`rca_console.html`) — **no libraries, no CDN, no build**.
- Live SQL needs the `backend/` (FastAPI + pyODBC), `backend/config.json` (gitignored), the ODBC Driver 17/18, and network access to SQL Server. Data table: `Playground.dbo.Input_To_ML` on `10.10.9.75`.
- Two metrics only — **Forecast Accuracy** and **Forecast Adherence** (signed); flag when `|adherence| > band`. **Never change the formula math**, and **never fabricate data/schema/credentials.**

Details: `AGENTS.md`, `IMP_DOCS/installation-and-connection.md`, `DEPLOY.md`.
