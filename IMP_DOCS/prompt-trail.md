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

---

## Session 10 — 2026-07-24 · ⓘ hint on the Fiscal Week filter
Requested → delivered:
1. Added an **ⓘ button** next to the Fiscal Week filter — hover shows a tooltip ("type/pick a week and press Enter → popup of affected queues"); clicking it opens the affected-queues popup when a week is already selected, otherwise shows the tip.
2. Reinforced the affordance: the field hint now reads "Enter → affected queues". Typing/picking a week and pressing **Enter** (or selecting from the datalist) opens the affected-queues popup — behaviour confirmed.

Verification: all `<script>` blocks validated via `new Function(...)` — OK.

---

## Session 11 — 2026-07-24 · Truncate data to 2025-2027
Requested → delivered:
1. **Deleted 2022–2024 and 2028–2029** from `Playground.dbo.Input_To_ML` — kept **strictly 2025–2027** (`Fiscal_Week` 202500–202799). **138,775 → 66,612 rows** (verified: range now 202501..202752; years 2025/2026/2027). Reversible — the Excel still holds all years.
2. **Persisted the cut in the loader** — added a Fiscal_Week range filter to `upload_excel_to_sql.py` (`--min-week`/`--max-week` + config `min_fiscal_week`/`max_fiscal_week`). `config.json` set to 202500–202799 (password untouched); `config.example.json` documents it. So re-running the loader stays truncated.

Verification: SQL `COUNT(*)` after = 66,612; loader `py_compile` OK; dry-run filter kept 66,612 of 138,775.

---

## Session 12 — 2026-07-24 · Confirm + IMP_DOCS refresh
Requested → delivered:
1. **Confirmed everything**: SQL = **66,612 rows, Fiscal_Week 202501–202752 (FY2025–2027)**; backend `/api/health` returns `configured:true`.
2. **Refreshed IMP_DOCS** to the current state: `design-choice.md` (data scope 66,612 + loader filter + a "Sessions 7–11" summary), `handoff.md` (state of play, files table incl. run scripts + AI runbook, row count), `TODO.md` (sessions 7–11 Done block), `AGENTS.md` (row count/scope + loader filter).

---

## Session 13 — 2026-07-27 · RCA engine v2 + business-report polish (shivam-updates, then merged main)
Done on branch `shivam-updates` (earlier branch work — the "Forecast Adherence" rename, deviation colour-bands, flagged-% KPI, right-side Insights drawer — already reached main via merge `babf5a1`, so it isn't re-logged here). Then `origin/main` (Sessions 3–12 above) was merged back into `shivam-updates`; conflicts in `config.example.json` and the IMP_DOCS were resolved keeping both sides.
Requested → delivered:
1. **Fixed "same root cause for every queue"** — grounded in the live SQL data. `backend/rca_investigate.py` now runs two deterministic passes around the LLM: `derive_features()` (field hygiene — drops noise cols `Fiscal_Week`/`Week_Ending`/`Monday–Sunday`, collapses `Final_Y*` — plus discriminating per-queue features: forecast-sanity, chronic bias, this-week-vs-usual, peer divergence, plan restatement, installed base, holiday), and `_verify_and_fix()` (rejects circular "the miss is the cause" answers). Cause is classified into a `cause_type` taxonomy.
2. **Per-queue AI model picker** — `GET /api/models` (reachable models only) + `?provider=&model=`. Verified-reachable set: Nemotron-3-Super-120B (default), DeepSeek-V4-Flash, Nemotron-Super-49B, Nemotron-3-Ultra-550B (flaky), Groq Llama-3.3. A picked model that fails is **not** silently answered by another — the deterministic finding is returned. `_chat_json` retries without `response_format` for models that reject it. (NVIDIA `/v1/models` lists models not provisioned per account — verified ids live.)
3. **Plain business language** — every human-facing sentence jargon-free (no z-score/stdev/outlier); technical scores kept in evidence chips / `source_field`.
4. **Distinct report sections** — Key Findings (objective observations) ≠ Root Cause (the why) ≠ Reasoning (the story, bulleted); Rejected Hypotheses in plain "checked & ruled out" language; confidence bar coloured by level; `_fill_gaps()` guarantees no blank card even on a sparse model reply.
5. **Definitions tab** made business-accurate — Fiscal_Week calendar (Sat start / Fri last working day / FY from 1st week of Feb), Region AMER/LATAM, Offering tiers, channels, **ASU as its own field**, `Final_Units` Y1–Y5 overlap note, Monday–Sunday = holiday; removed the `formula` field and all "ML/Manual" labelling; **Severity tile removed**.
Verification: `node --check` (frontend) + `py_compile`/AST (backend); live end-to-end against real SQL queues across models (per-queue differentiation, model comparison, honest fallback all confirmed); deterministic gap-fill unit-checked offline.

---

## Session 14 — 2026-07-27 · Glossary to the model + data-backed proof + report readability
Requested → delivered:
1. **Field glossary fed to the LLM** — `FIELD_DEFINITIONS` (mirrored from the Definitions tab; kept in sync) injected as `field_glossary` (present fields only) into the model context, plus a prompt line telling it to interpret fields via the glossary (ASU = units under warranty; `Final_Y1..Y5` nested) and never repeat a definition as a finding. Live: the model now expands and reasons about ASU correctly.
2. **Definitions tab** — `Actual_Offered`/`Actual_Handled`/`fcst_offered`/`fcst_handled` set to plain "…volume" definitions; `ASU`/`Planned_ASU`/`Actual_ASU` to Active-Serviceable-Units wording (per the client's reference).
3. **Data-backed proof, z-scores internal-only** — the reasoning stays plain English but is now backed by the **actual values from the data**. `derive_features()` adds real "usual" levels + a `proof` list (forecast, actual, ASU, installed base, holidays — this-week vs usual); a new **"Proof — values from the data"** panel renders them; `supporting_evidence.value` must be a real number (prompt-enforced), never a z-score/deviation. z-scores still reach the model as reasoning input, just never shown. Live-verified: evidence cites real numbers, zero jargon leaked.
4. **Readability** — evidence chips switched to dark-blue text (`#123a7a`, bolder, stronger border) — the light-blue text was hard to read.
5. **Process** — user asked that **IMP_DOCS be updated after every approved change**; `design-choice.md` ("RCA engine v2" section) and this trail brought current, and the standing instruction recorded.
Verification: `node --check` (frontend) + AST (backend); offline check that proof/evidence carry real values; live Groq call confirmed real-number evidence + ASU expansion + no z-score/deviation leakage.
