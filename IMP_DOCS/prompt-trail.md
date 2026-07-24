# Prompt Trail — Demand Pattern RCA Console

Chronological record of what was requested and what was delivered. Newest at the bottom.

---

## Session 1 — 2026-07-22 · Console fixes & first enhancements
**Source file:** `~/Downloads/rca_console.html` (single self-contained HTML, no libraries)
**Input data understood:** `Input_To_ML_20260706110242.csv.xlsx` — 33 columns, 138,775 rows, Fiscal_Week 202249→202908.

Requested → delivered:
1. **Add filters** — Forecaster, Offering, Projection_plan_name, channel, business_org → filter set expanded to all **10** business dimensions (Fiscal_Week, Region, SubRegion, Country, Forecast_name, Forecaster, Offering, Projection_plan_name, channel, business_org).
2. **Rename `fcst_offered` → "forecast offered (Simple)"** in the report, evidence trail and math modal, and **format its value to 2 decimals** — display only, the underlying calculation is untouched.
3. **Fix the stray `''`** after "Fiscal Week 2027nn" in the report meta line.
4. **Fix "Avg Accuracy"** — it was showing ~99% (impossible). Root cause: a plain mean of `Actual÷Fcst` lets over/under-forecasts cancel. Replaced with **100 − MAPE** (mean absolute % error = mean Plan-Adherence deviation). Full-file value = **77.1%**.
5. **Volumetrics on load** in "EPIC form" — dark hero panel with headline KPIs + a per-dimension breakdown across the 10 selected dimensions; reactive to the active filters.
6. **Probing layer — "what more can be done"** — added dimension-aware static probes plus **data-driven auto-probes** (plan restatements, top flagged forecaster, unscoreable data-gap rows), a **category tag**, and captured **queue/week context** saved into the KB and its Markdown export.

Verification: syntax-checked; ran the actual scan engine against real sampled rows via a DOM-stub harness (avg accuracy 77–84% depending on slice, 2-dp value confirmed, stray quote gone).

---

## Session 2 — 2026-07-22 · Dashboard, graphs & timeline
Requested → delivered:
1. **Improve volumetrics per design guidance** — applied the `dataviz` skill (form-first, sequential-blue + status palette, no dual-axis, no cycled categorical hues).
2. **Project folder** — created `~/Documents/RCA Console/` with every required file (`rca_console.html`, `rca_timeline.html`, `IMP_DOCS/`). The Excel file is **not** included by request.
3. **New "Dashboard" nav tab** — moved volumetrics here and added graphs + data points:
   - Actual offered by fiscal week (area/line, crosshair tooltip)
   - Forecast accuracy by fiscal week (area/line, crosshair tooltip)
   - Forecast-accuracy deviation spread (status-coloured, labelled)
   - Top flagged forecast names (bars)
   - Actual offered by Region / Channel / Offering (bars)
   - 10-dimension cardinality & mix breakdown (EPIC hero)
4. **Deadline Gantt in the UI** — new "Timeline" nav tab embedding the build Gantt; also **updated the standalone** `rca_timeline.html` (today marker → 22 Jul, KPIs 8-days / 4✓, phase statuses refreshed, calc-risk marked resolved).
5. **IMP_DOCS** — this file plus `design-choice.md`, `handoff.md`, `TODO.md`.
6. Opened the project folder in VS Code.

Verification: extracted the `<script>`, `node --check` passed; ran the scan+dashboard render through a DOM-stub harness on real rows (2 trend blocks, 7 chart cards); headless-Chrome screenshots of the Console, Dashboard and Timeline tabs reviewed and confirmed.

---

## Sessions 3–5 — 2026-07-23 · Live SQL Server (AA) + deployment
Requested → delivered:
1. **Working SQL Server connection** — added a **FastAPI + pyODBC** backend (`backend/sql_backend.py`, `/api/health`, `/api/data`), an **Excel→SQL loader** (`upload_excel_to_sql.py`), and wired the console's **"Connect to SQL Server (AA)"** button to `/api/data` (was a mockup). Loaded the full **138,775 rows** into **`Playground.dbo.Input_To_ML`** on server `10.10.9.75` (verified via `sys.tables` + `COUNT(*)`).
2. **Deployment package** — `Dockerfile` (bundles msodbcsql18) + `docker-compose.yml` + env-var secrets + `DEPLOY.md` (Docker / Windows-service / systemd) for always-on internal hosting.
3. **Docs** — `IMP_DOCS/installation-and-connection.md` (setup + connection + troubleshooting) and updates to handoff/TODO/design-choice.
4. **Timeline** — plain-English step names, **auto-date from the PC clock**, added **"RCA output — report per queue"** (10 steps), light-only.

Verification: uploader dry-run on the real 138,775-row file; backend routes tested (health/data/static); pyodbc install + live COUNT confirmed; all `<script>` blocks syntax-checked.

---

## Session 6 — 2026-07-24 · Merge Shivam's dashboard + dashboard filters + loading screen
Requested → delivered:
1. **Merged `origin/shivam-updates` into main** (clean, merge `babf5a1`) — kept both feature sets (his dashboard + our SQL/timeline); his branch left untouched ("on check").
2. **IMP_DOCS reconciled** — documented his **"Plan Adherence" → "Forecast Adherence"** (now **signed**) rename, deviation colour-bands, flagged-% KPI, Insights drawer, deep-dive/exploration-trace UI.
3. **Dashboard dropdown filters** — `Region, Sub-Region, Country, Channel, Offering, Forecaster, Projection plan` selects that drive the existing scan engine, so the graphs recompute the **affected (flagged) queues** for the selection.
4. **Data-ingestion loading screen** — full-screen overlay with a 6-step progress list (read → parse → build → compute → flag → render) + progress bar, wired into **both** the file-upload and the SQL-fetch paths.

Verification: every `<script>` block validated via `new Function(...)` — all OK.
Known limitations: 2 legacy "Plan Adherence" strings still in the UI (cosmetic); the Console checkbox filters and Dashboard dropdowns both write the shared FILTERS state, so they can visually desync (last action wins).

> Process note: from here on, each prompt's work is appended to this trail.

---

## Session 7 — 2026-07-24 · Affected-queues-by-band chart
Requested → delivered:
1. New Dashboard chart **"Affected queues by Forecast-Adherence band"** — only flagged queues (|Forecast Adherence| > band), each bucketed by its **worst** week into **≤±15% / ±15–25% / ±25–50% / ±50–100% / >±100%**; value = distinct queues, note = % of affected queues + flagged weeks in the band. Reacts to the drill path and the console/dashboard filters.
2. Renamed the existing spread to **"Forecast Adherence spread — all weeks"** (was "Forecast-accuracy deviation spread") and reframed the copy around Forecast Adherence.

Verification: all `<script>` blocks validated via `new Function(...)` — OK.

---

## Session 8 — 2026-07-24 · Fiscal-Week typeable filter + name-by-band distribution
Requested → delivered:
1. **Fiscal Week filter — typeable (Excel-style)** in the Dashboard filter bar: a `<datalist>` type-ahead of all 325 weeks; accepts an exact week, a **partial** (`2024` → all FY24 weeks), a **comma list**, or a **range** `202401-202410`. Empty = all; no match = empty (Excel behaviour). Drives the same scan engine.
2. **Reworked the affected chart → "Forecast names by adherence band"**: every forecast name in scope bucketed by its worst week's |Forecast Adherence| into **≤±5 / ±5–10 / ±10–15 / ±15–20 / ±20–25 / >±25**. With a Fiscal Week selected, each name has one value that week, so it shows exactly which names sat at ±5, ±10, ±15–20… that week. Value = distinct names; note = share · weeks in band.

Verification: all `<script>` blocks validated via `new Function(...)` — OK.

---

## Session 9 — 2026-07-24 · Affected-queues popup + one-command runner + AI runbook
Requested → delivered:
1. **Affected-queues popup** — selecting a Fiscal Week opens a modal listing the **real flagged forecast names** for that scope: name, Fiscal Week, signed Forecast Adherence, band, direction. Sourced straight from `FLAGS` (computed rows) — nothing fabricated. Dismiss via ✕ / click-outside / Esc.
2. **One-command runner** — `run.ps1` (Windows) / `run.sh` (POSIX): installs deps, seeds `backend/config.json`, starts the backend and opens the app.
3. **AI runbook** — `AGENTS.md` (full: what it is, run paths, SQL setup, endpoints, guardrails, "if you are an AI agent" steps) + `CLAUDE.md` (auto-loaded pointer + quick start).

Verification: `rca_console.html` scripts validated via `new Function(...)`; `run.ps1` parsed clean (kept ASCII-only for PowerShell 5.1).
