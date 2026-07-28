# CLAUDE.md

**Read `AGENTS.md` first** — it's the full runbook for running this app (UI + SQL backend).

Quick start:
- **Windows (easiest):** `run.bat` — one shot: deps, config, VPN, SQL check, backend, browser.
  Add `--all` to also run the three test suites, `--smoke` for the 12-module test only.
- **Windows (PowerShell):** `powershell -ExecutionPolicy Bypass -File run.ps1`
- **Linux/macOS:** `./run.sh`
- **Docker:** `docker compose up -d --build` (see `DEPLOY.md`)
- **No install / no SQL:** open `rca_console.html` and use **Upload weekly file**.

Then open **http://localhost:8000/rca_console.html**.

Key facts:
- Front end is one self-contained file (`rca_console.html`) — **no libraries, no CDN, no build**.
- Live SQL needs the `backend/` (FastAPI + pyODBC), `backend/config.json` (gitignored), the ODBC Driver 17/18, and network access to SQL Server. Data table: `Playground.dbo.Input_To_ML` on `10.10.9.75`.
- Two metrics only — **Forecast Accuracy** and **Forecast Adherence** (signed); flag when `|adherence| > band`. **Never change the formula math**, and **never fabricate data/schema/credentials.**
- **Two RCA engines** behind `POST /api/rca-investigate`: the original (no parameter) and the
  **WFM engine** at `?mode=wfm` (`backend/wfm/`, 13 modules — ranked causes, a skeptic that
  rejects unsupported causes, investigation ladder, 104-week context, channel migration).
  It backfills the legacy response keys, so the UI needs no change.
- `llm.timeout_seconds` in `config.json` sets the LLM read timeout for both engines (150 now;
  NVIDIA needs 45–100s, Groq has a 100k token/**day** cap).
- Evidence and re-runnable tests live in `results/` — start with `results/audit-log.md`.

Details: `AGENTS.md`, `IMP_DOCS/wfm-rca-engine.md`, `IMP_DOCS/installation-and-connection.md`,
`IMP_DOCS/canary-test-log.md`, `DEPLOY.md`.
