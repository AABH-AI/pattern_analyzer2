# TODO — Demand Pattern RCA Console

Deploy **30 Jul 2026** · last dev day **29 Jul**. Ordered by priority.

## P0 — critical path to the mockup
- [x] **P6 · Connect to SQL Server (AA)** — **DONE.** Live ingestion via FastAPI + pyODBC backend (`GET /api/data`); 138,775 rows loaded into `Playground.dbo.Input_To_ML`; console button wired; hosting packaged (Docker/Windows-service/systemd). See `IMP_DOCS/installation-and-connection.md`.
- [ ] **P4 · Phase-1 digest** — one-click export of *all* flagged queues (multi-queue scan → top-N → printable/report page). Main remaining build.
- [ ] **P7 · Validation with Prashant / SME** on the full real dataset — must land by **28 Jul** to keep a buffer day.
- [ ] **Confirm the adherence band** — ±10% vs ±15%, and whether it tiers by `Volume_Category`. Blocks tuning.
- [ ] **P8 · Demo packaging + dry run** (28–29 Jul) — walkthrough script, rehearsal, digest export sanity check.

## P1 — correctness / data questions to close (probing layer)
- [ ] Source of truth for adherence — **Offered vs Handled**?
- [ ] On **Projection_plan restatement** mid-cycle, is the miss forgiven? (auto-probe already flags restated queues)
- [ ] Exact meaning of **ASU** (Planned/Actual).
- [ ] Treatment of **holiday weeks** (`Holiday_Count > 0`).
- [ ] Per-**Offering** / per-**Channel** acceptable bands, if any.

## P2 — dashboard / UX polish (post-deadline OK)
- [x] High-cardinality dimension cards showed 0% shares — now show row counts; Fiscal_Week dropped from the grid; panel made bolder/cleaner. (2026-07-22)
- [ ] Trend charts: optional brush/zoom for the 325-week span; shared hover legend across the two trend charts.
- [ ] Export the Dashboard as a PNG/PDF for the digest.
- [ ] Consider a light/dark toggle for the console itself (timeline already themes; console is light-only).

## P3 — architecture phase (out of 30 Jul scope)
- [ ] On-prem **LLaMA narration** layer (explains drivers; never computes).
- [ ] Wire the two metrics as **MCP tools** + SQL metric views.
- [ ] RAG over the probing KB to auto-surface known causes on matching queues.
- [ ] Let confirmed KB rules feed back into flag suppression / re-flagging.

## Done ✓ (2026-07-24, session 6 — merge Shivam's dashboard + timeline polish)
- [x] Merged `origin/shivam-updates` into main (clean, merge `babf5a1`) — both feature sets intact; his branch left untouched (0 ahead of main)
- [x] **"Plan Adherence" → "Forecast Adherence"**, now **signed** (− = actual above forecast, + = below); flag on **|Forecast Adherence| > band**
- [x] Dashboard: deviation colour-bands, flagged-% KPI, right-side **Insights drawer**, signed adherence, **agentic deep-dive / exploration-trace** UI (Shivam)
- [x] Timeline: added **"RCA output — report per queue"** (now 10 steps); **auto-date from the PC clock**; plain-English step names; light-only
- [ ] Cosmetic: clean up the last 2 legacy "Plan Adherence" strings in the UI (notes card + code comment)

## Done ✓ (2026-07-23, session 5 — SQL Server (AA) live)
- [x] FastAPI + pyODBC backend (`backend/sql_backend.py`): `/api/health`, `/api/data` (`SELECT * FROM <table>`), also serves the UI
- [x] Excel→SQL loader (`upload_excel_to_sql.py`, `--dry-run` / `--schema-only`) — loaded **138,775 rows** into `Playground.dbo.Input_To_ML`
- [x] Console "Connect to SQL Server (AA)" wired to `/api/data` (was a file-picker mock); modal shows real server/db/table
- [x] Deployment package: `Dockerfile` (bundles msodbcsql18) + `docker-compose.yml` + env-var secrets + `DEPLOY.md`
- [x] Timeline renames: P2 → "Accuracy & Error Computation (100-MAPE)", P5 → "Data Volumetrics"; P6 marked Done
- [x] `IMP_DOCS/installation-and-connection.md` added

## Done ✓ (2026-07-22, session 4 — RCA analytics bundle)
- [x] Actual-vs-Forecast weekly overlay (two-series, one y-scale)
- [x] Signed forecast bias (diverging) by Region + top over/under-forecast queues
- [x] Rule-based auto-insight callouts (scope-aware) + KPI delta vs baseline on drill

## Done ✓ (2026-07-22, session 3)
- [x] Volumetrics **drill-down** — click any dimension value to re-scope the whole panel card-by-card; breadcrumb + clear; expandable member lists; row counts (not 0% shares)
- [x] Pushed project to GitHub `AABH-AI/pattern_analyzer2` (public) + `index.html` Pages entry

## Done ✓ (2026-07-22)
- [x] 10-dimension filters
- [x] `fcst_offered` → "forecast offered (Simple)", 2-dp display (calc intact)
- [x] Stray `''` after Fiscal Week removed
- [x] Avg Accuracy → 100 − MAPE (77.1% full file)
- [x] EPIC volumetrics + **Dashboard** tab with graphs
- [x] Data-driven probing auto-probes + category + captured context
- [x] Deadline **Gantt** embedded (Timeline tab) + standalone `rca_timeline.html` refreshed
- [x] Project folder + IMP_DOCS
