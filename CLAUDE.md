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
- Live SQL needs the `backend/` (FastAPI + pyODBC), `backend/config.json` (gitignored), the ODBC Driver 17/18, and network access to SQL Server. Data table: **`Playground.dbo.Input_To_ML_Full_138_Trimmed`** on `10.10.9.75` — 114,436 rows, 427 queues, fiscal weeks 202401–202908, **32 columns**. `Projection_plan_name` was dropped from it (commit `5b1cdf7`); earlier tables `dbo.Input_To_ML_Full_138`, `dbo.Input_To_ML_Full` and `dbo.Input_To_ML` remain in place and still carry that column.
- Two metrics only — **Forecast Accuracy** and **Forecast Adherence** (signed); flag when `|adherence| > band`. **Never change the formula math**, and **never fabricate data/schema/credentials.**
- **Three RCA engines** behind `POST /api/rca-investigate`:
  - the original (`?mode=legacy`, or no parameter on older builds),
  - the **WFM engine** at `?mode=wfm` (`backend/wfm/`, 13 modules — ranked causes, a skeptic that
    rejects unsupported causes, investigation ladder, 104-week context, channel migration).
    It backfills the legacy response keys, so the UI needs no change.
  - the **FC Decision Card engine** at `?mode=spec` — the canonical 15-step FC RCA methodology and
    the Executive Decision Card. Answers *why did the forecast miss* with one of seven mechanisms, a
    four-condition forecastability gate, lag-aware driver evidence, pre/holiday/post phases,
    criticality separate from confidence, and a direction-coherence gate that runs before confidence.
    See `IMP_DOCS/fc-decision-card-engine.md`.

  The engines are **independent**. They may be compared on the same input; neither is made to match
  the other. `?mode=spec` returns its own shape (the UI detects `decision_card`); `?mode=wfm` fills
  the legacy keys.
- `llm.timeout_seconds` in `config.json` sets the LLM read timeout for both engines (150 now;
  NVIDIA needs 45–100s, Groq has a 100k token/**day** cap).
- Evidence and re-runnable tests live in `results/` — start with `results/audit-log.md`.

Test suites (all runnable without SQL except the last):
```
python results/test_fc_spec_semantics.py          # FC Decision Card — 189 checks, 24 brief scenarios
python results/test_wfm_diagnostics.py            # the shared diagnostic modules — 148 checks
python results/smoke_test_modules.py              # 12 modules load and wire up
node   results/check_ui_render.js                 # the REAL renderers over REAL captured responses
cd backend && python ../results/run_offline_investigation.py     # offline, no SQL, no model
cd backend && python ../results/run_live_spec_validation.py  # live SQL + live model
```
`run_live_spec_validation.py` uses port **8011**, not 8000, and refuses to start if anything is
already listening — a stale server on 8000 silently answered part of a run with pre-upgrade code.

Details: `AGENTS.md`, `IMP_DOCS/fc-decision-card-engine.md`, `IMP_DOCS/wfm-rca-engine.md`,
`IMP_DOCS/installation-and-connection.md`, `IMP_DOCS/canary-test-log.md`, `DEPLOY.md`.
