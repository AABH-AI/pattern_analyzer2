# Prompt Trail — Demand Pattern RCA Console

Chronological record of what was requested and what was delivered. Newest at the bottom.

---


> **Timestamp convention (from Session 19 onward).** Each session records **When** — the
> local wall-clock window the work was actually done in, `Asia/Kolkata (IST, UTC+05:30)` —
> plus **Runtime**, the measured execution time of the things that were built. Times are
> reconstructed from commit timestamps and artifact mtimes, so they are accurate to the minute
> rather than to the second. Sessions 1-18 predate this convention and carry dates only.

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

---

## Session 15 — 2026-07-27 · 13-week window + manager-readable proof + forecast-vs-actual fix
Requested → delivered:
1. **History window 12 → 13 weeks** — `RCA_HISTORY_CAP=13` (frontend) and `/api/queue-context` `history_cap=13`; "usual" comparisons now use 13 weeks. Docs updated.
2. **Manager-readable proof** — the "Proof — values from the data" panel gains a plain **"vs usual"** column ("about 143x higher than usual" / "about the same as usual"), a **"Usual (13 wks)"** header, cleaner rounding (whole numbers for big counts), and drops the noisy "0 holidays (usual ~0.08)" row. Prompt now requires every sentence to state the number AND what it means so a manager can read it standalone.
3. **Correctness fix — forecast anomaly vs actual anomaly.** A screenshot case (forecast ~91 ≈ usual ~98, actual 8,805 vs usual ~62) was wrongly labelled `forecast_baseline_error`. `forecast_sanity` no longer blames the forecast just because forecast≪actual: `forecast_anomalously_low/high` only when the forecast is off vs its own history; a normal forecast with a spiking actual is `actual_anomalous` → **`genuine_demand_event`**. Verified: the same case now reads "Actual demand was 8805 — far from the usual ~62 — while the forecast (90.78) was about normal … a real change in demand, not a forecasting error."
Verification: `node --check` (frontend) + AST (backend); live deterministic + Groq runs confirmed the new proof column and the corrected classification.

---

## Session 16 — 2026-07-27 · Empty-"usual" fix + drop handled from RCA + proof cleanup
Requested → delivered:
1. **Bug: "Usual (13 wks)" showed blank.** Root cause: in file mode, history/peers were built from `ROWS.filter(passFilters)`, so an active Fiscal_Week filter stripped the queue's prior weeks → empty history → blank "usual". Fixed `aggregateData` to gather history (same Forecast_name, chronological, strictly before the target week) and peers from the **full `ROWS`**, hydrating rows so they carry `_ao/_fo/_padh/_wk`. (SQL mode already queried full data.) Confirmed the engine returns 13 weeks + populated "usual" on a real queue.
2. **Removed the "vs usual" change column** from the Proof panel (kept the **Usual (13 wks)** column) per request.
3. **Removed `Forecast (fcst_handled)` and `Actual handled` rows** from the Proof panel.
4. **Excluded all "handled" fields from the RCA** (`HANDLED_FIELDS = {Actual_Handled, fcst_handled}`): stripped from the model context (statistical_summary, target fields, glossary), the cleaned signals, and the proof. Verified nothing handled-related reaches the model.
Verification: `node --check` (frontend) + AST (backend); offline check that proof/model context carry no handled fields and "usual" still populates from history.

---

## Session 19 — 2026-07-28 · WFM business prompt as a second engine (branch `wfm-rca`)
**When:** Tue 28 Jul 2026, ~19:00–20:15 IST · **Runtime:** in-band gate 0.60s · full WFM run (Groq) 3.65s · default engine ~4s · payload ~4,400 tokens/investigation (prompt ~2,300 + data ~2,100).
The business supplied a complete RCA specification (cross-functional-team ROLE, fixed
investigation order, temporal rules, CQN/channel-migration rules, SKEPTIC MODE, Top-5 ranked
RCAs, hypothesis marking, confidence levels, executive report format). Delivered on a NEW
branch `wfm-rca` off `shivam-updates`, as an **additive opt-in engine** — see
`IMP_DOCS/wfm-rca-engine.md` for the full contract.

1. **New `backend/rca_wfm.py`** carrying the prompt verbatim in substance, with only a JSON
   output contract appended (the engine has to parse the reply).
2. **`?mode=wfm` on `POST /api/rca-investigate`.** Without it the endpoint behaves exactly as
   before. `backend/rca_investigate.py` changed by **zero lines** and `rca_console.html` by
   **zero lines** — confirmed by an empty `git diff --stat` against `shivam-updates`.
3. **The spec needed data, not just wording.** Added server-side fetches the old bundle never
   had: 104-week history + same-week-last-year; an **investigation ladder** (adherence
   recomputed at org/region/subregion/country/channel for the same week, so a queue-level
   conclusion is never reported before checking inheritance); and **channel siblings** (the
   locality across ALL channels — the old peer query filtered to the *same* channel, so
   channel migration was structurally undetectable). Fetched from the target row's own
   identifiers, which is why the console needs no change.
4. **Threshold gate.** Within ±band returns `engine: wfm-not-investigated` and no causes, per
   "never investigate KPIs within the acceptable threshold".
5. **Arithmetic stays in Python.** `kpi_status` and the channel-migration verdict are computed
   and then *overwrite* whatever the model said. The model ranks, explains, challenges.
6. **Back-compat.** Rank 1 → `primary_root_cause`/`cause_type`/`confidence_score`, ranks 2-5 →
   `secondary_contributors`, rejected challenges → `rejected_hypotheses`. All 11 legacy keys
   verified present, so the current UI renders a WFM report unmodified.
7. **Added a data-quality gate (not in the supplied spec).** "Never fabricate business events"
   implies checking the number is real before explaining it. Flags an actual that is ≥10x or
   ≤0.1x the typical week, is the only week near that level, and reverts immediately — as a
   *hypothesis to validate at source*, never as an asserted cause.

**This revises Session 15.** That session reclassified `NA Core Spanish` 202719 (actual 8,805
vs usual ~62) from `forecast_baseline_error` to `genuine_demand_event`. Evidence now says it is
probably neither: across 126 weeks the queue ranges 31–8,805 with **exactly one** week over
1,000; the next weeks are 87/54/39; of 427 queues with ≥8 weeks it is the **only** one with a
week >50x its own median; the warranty base barely moves; and `8805/100 = 88.05` against that
week's forecast of `90.78`. The cumulative-backfill alternative was tested and rejected (52wk
sum 4,752, 104wk 11,697 — no match). The WFM engine now ranks **"Suspected data quality issue"
#1 at 90% (High)** for this case. The figure should be validated at source.

Verification: AST (backend); empty diffstat vs `shivam-updates` for the old engine + UI; live
Groq runs for all three engine states (`wfm-llm`, `wfm-not-investigated`,
`wfm-deterministic-fallback`); default mode confirmed unchanged and free of WFM keys; SQL fetch
confirmed returning 104 history / 4 forward / 92 channel-sibling / 5 ladder rows.

**Still open (largest gaps):** no evaluation set, so ranking *correctness* remains unmeasured;
`correlation_engine` unimplemented, so the prompt asks for ASU↔demand and holiday↔demand
relationships nothing has computed; and the exact `Planned_ASU`/`Actual_ASU` driver
decomposition (verified identity-exact on 22,003 flagged misses) is not yet a signal.

---

## Session 20 — 2026-07-28 · WFM engine split into reasoning modules + the two missing ones
**When:** Tue 28 Jul 2026, ~21:40–22:35 IST (modules written 21:48; SQL re-verified 22:30) · **Runtime:** `fetch_wfm_context` **98.19s → 0.16s (614x)** after removing the correlated subquery · full WFM path (Groq) 3.12s · SQL-backed WFM run 3.63s · in-band gate 0.47s.
Requested: refactor the single `rca_wfm.py` into separate reasoning modules and add the two
that were missing. Delivered on the same branch `wfm-rca`.

1. **`backend/wfm/` package, 13 modules** — `investigation_engine`, `hierarchy_analyzer`,
   `channel_migration_detector`, `temporal_reasoner`, `correlation_engine`,
   `hypothesis_generator`, `skeptic`, `business_report_generator`, plus `data_quality`,
   `data_access`, `prompts`, `common`, `__init__`. `backend/rca_wfm.py` is now a
   compatibility shim, so `from rca_wfm import ...` still works.
   Rationale worth recording: file layout does not give the model "clearer responsibilities" —
   it never sees the directory. The win is that each responsibility becomes **deterministic
   Python instead of a prompt instruction**, which makes it testable and unfakeable.
2. **`skeptic.py` — rejection in code (the highest-value fix).** SKEPTIC MODE was prompt-side
   only; nothing could reject anything. Now: a feature **precondition** for all 10 cause types
   (no trace in the features ⇒ the cause is impossible, hard reject), plus **numeric grounding**
   of every cited figure against the real numbers (2% tolerance; unreconciled figures are
   pruned, which deliberately does not kill the cause). Verified: a `plan_restatement` claim on
   a week where the plan did not change is now rejected — the old engine published it.
   `eligible_cause_types()` is fed to the prompt so a slot is not wasted on a doomed type.
   Required adding `cause_type` to each ranked cause in the output contract — without a
   machine-readable type nothing can be gated.
3. **`correlation_engine.py` — the gap that mattered.** The prompt asked for ASU↔demand and
   holiday↔demand relationships "consistently supported by history" while nothing computed
   them, so the model was being asked for correlations it had no numbers for. Now: Spearman
   rank correlation per driver (rank-based so the extreme week that triggered the
   investigation does not drag it), retained/rejected against explicit thresholds (≥12 weeks,
   |strength| ≥ 0.5), each retained entry carrying a jargon-free sentence with the coefficient
   confined to the collapsed technical section. Plus the **exact ASU driver decomposition**:
   `volume=(Actual_ASU−Planned_ASU)×planned_rate`, `rate=Actual_ASU×(actual_rate−planned_rate)`,
   summing identically to the total miss — verified exact on all 22,003 flagged misses carrying
   both columns (60.7% rate-driven, 9.8% base-driven, 29.6% mixed).
4. **`hypothesis_generator.mark()`** downgrades over-confident statuses structurally: a
   `data_quality_issue` (needs source validation) or a `channel_migration` (computed on a CQN
   *proxy*) can never be "Verified", and a cause with no surviving evidence is downgraded too.

**Bug found and fixed in my own earlier code:** the channel-sibling query resolved the prior
week with a correlated subquery. On this un-indexed table that measured **101.5s** while every
other query ran in 0.02–0.05s — an investigation appeared to hang. The prior week is already
known from the 104-week history, so it is passed as a literal: **98.19s → 0.16s (614×)**,
identical results.

Verification: AST on all 16 backend files; package + shim + `sql_backend` imports; empty
diffstat vs `shivam-updates` for the old engine and the UI; default mode unchanged with no WFM
keys leaked; in-band gate correct; full WFM path via Groq in **3.12s** ranking
`data_quality_issue` first (auto-downgraded to Hypothesis) with both model-side and code-side
skeptic entries; unit checks on both new modules.

**Caveat:** late in the session SQL host `10.10.9.75:1433` became unreachable (`Named Pipes
Provider … Login timeout expired`), so the SQL-backed fetches (104-week / ladder / channel
siblings) could not be re-run after the refactor — they were verified before it. The full
pipeline was exercised in-process with a context built from the bundle's own history.
**Re-run the SQL-backed path once the network is back.** Also logged: a dead SQL host makes a
`?mode=wfm` request wait ~42s before degrading (the fetch is non-fatal, but the ODBC login
timeout dominates).

---

## Session 21 — 2026-07-28 · configurable LLM timeout + LLM ranking verified + Canary V0.2
**When:** Tue 28 Jul 2026, ~22:40–23:20 IST (llm_client 22:59; ranking report 23:13; engine doc 23:15) · **Runtime:** NVIDIA WFM investigations 53.4s / 59.2s / 67.9s · Groq 2.4–5.7s · Canary V0.2 session 15min/25 steps.
Requested: get 2–3 LLM outputs to verify model ranking, and **it must actually use the LLM**;
capture an updated Canary screen recording end to end; keep IMP_DOCS current.

1. **`wfm/llm_client.py` — LLM transport with a configurable timeout.** `llm.timeout_seconds`
   in `config.json` (set to 300). Deliberately a SEPARATE transport rather than editing
   `rca_investigate._call_openai_compatible`, so `rca_investigate.py` stays byte-identical to
   `shivam-updates` and the original engine cannot regress — it keeps its own 100s. Preserves
   both hard-won behaviours: the browser-like User-Agent (Groq's Cloudflare 403s the default
   urllib UA) and the retry without `response_format` (some NVIDIA models 400/503 on it).
2. **LLM ranking verified — 3/3 queues answered by the model, 27/27 checks passed.**
   `results/run_llm_ranking.py`, NVIDIA `nemotron-3-super-120b-a12b`, 53–68s each. Checks L1–L9
   assert the engine really used the LLM (a deterministic fallback is a FAILURE of that run),
   ranks are sequential, confidence descends with rank, confidence_level matches its band, every
   shipped cause_type satisfies its precondition, the ladder's `inherited_from` is actually
   ranked, `data_quality.suspect` forces `data_quality_issue` FIRST, no banned statistics
   vocabulary, and every cause carries an action and a status.
   Ranking quality worth noting: on `NA Core Spanish` FW202719 the model produced 5 ranked
   causes, put `data_quality_issue` first at 92%, and ranked `genuine_demand_event` **last at
   12%** titled "Unlikely genuine demand surge" — i.e. it actively deprioritised the cause the
   ORIGINAL engine had concluded (Session 15). That is the intended behaviour arriving.
3. **Groq's binding limit is the DAILY quota, not the per-minute one.** 100,000 tokens/day,
   exhausted by the day's testing (`Used 98586`). Per-minute pacing cannot help. NVIDIA plus the
   raised timeout is the working combination once Groq is spent.
4. **Diagnostic fix.** When every model-proposed cause is rejected the engine fell back with an
   opaque "produced no cause the data supports". It now records what was proposed, each rejection
   reason, and which cause types the data actually supports. Found while investigating two
   fallbacks that turned out to be model run-to-run variance in chosen cause types, not
   over-rejection — verified by replaying the same queue directly, where the skeptic retained
   both proposals.
5. **Canary V0.2** — 25-step end-to-end session with video; recording copied into
   `results/canary-v0.2/` (25 MB). **3 new bugs**, the worst being that flagged-queue cards may
   not be clickable by a real pointer (`#filters` search input and a `.nav` anchor intercept
   pointer events over the list; the test only proceeded via `element.click()`). Also: changing
   the AI model re-runs the PREVIOUS queue and overwrites the panel. Logged as P1d.
   Re-confirmed still unfixed from V0.1: the `renderProbe` TypeError on every load, and the
   adherence-band chart reading `0 names · 0%` in 5 of 6 bands.

Honest note on causality: NVIDIA completed these runs in 53–68s, which is **inside** the old
100s, so the raised timeout was not what unblocked them — what varies is the model's choice of
cause types. The raised timeout remains correct insurance (an earlier NVIDIA call on the default
engine did exceed 100s), but it should not be credited with this result.

Evidence: `results/` — `llm-ranking-report.json`, three raw LLM responses,
`llm-ranking-console-output.txt`, `canary-v0.2/`, plus the earlier `validation-report.json`
(40/40 SQL cross-checks).

---

## Session 22 — 2026-07-29 · run.bat, module smoke test, timing log, commit
**When:** Tue 28 Jul 23:50 – Wed 29 Jul 00:45 IST — the date rolled over mid-session (Canary V0.3 investigations stamped 11:50 PM and 11:56 PM on the 28th; canary-test-log 00:14; smoke test 00:26; run.bat 00:40; **commit `254af93` at 00:45 IST on Wed 29 Jul 2026**).
Requested: commit the work to a new branch; confirm each Python module works; a `run.bat` that
runs the whole system including VPN if possible; and timings recorded here.

1. **`results/smoke_test_modules.py` — every module exercised in isolation.** **12/12 pass**,
   including the SQL fetches. Each check asserts behaviour, not just importability: KPI sign
   convention both ways, the ladder picking the highest *same-direction* level (and ignoring an
   opposite-direction breach), an offsetting channel move detected while joint growth is
   rejected, an isolated reverting spike flagged while a level shift is not, the decomposition
   identity, `plan_restatement` rejected when the plan did not change, a fabricated evidence
   figure pruned, `data_quality_issue` never allowed to be "Verified", the confidence band
   derived rather than trusted, and the in-band gate refusing without calling any provider.
   Runtime ~3s (module 10 hits SQL).
2. **`run.bat`** — 9 stages: Python check, deps, ensure `config.json`, **VPN** (detects Cisco
   Secure Client 5.1.9.113, checks `vpncli status`, tries `connect aavpn.alignedautomation.com`,
   falls back to launching the UI for SAML/MFA and polls up to 90s for the tunnel), SQL
   reachability read from `config.json` rather than hardcoded, frees port 8000, starts the
   backend and waits on `/api/health`, optional `--smoke` / `--validate` / `--llm` / `--all`
   suites, then opens the console. Flags: `--no-vpn`, `--no-browser`, `--tests-only`.
3. **Restored `backend/.env.example` and `backend/config.example.json`**, deleted before this
   session. `run.ps1:19` and `run.sh:16` both copy `config.example.json` to create
   `config.json`, so its absence broke first-run setup for anyone cloning the repo.
4. **Secret scan before committing** — 93 candidate files scanned for `nvapi-`, `gsk_` and the
   SQL password literal: clean. `backend/config.json` and `backend/.env` are gitignored.

### Measured timings — consolidated reference

| Operation | Time | Notes |
|---|---|---|
| `GET /api/health` | <50ms | |
| `GET /api/data` (full table) | 12.7–14.6s | 66,612 rows x 33 cols |
| `GET /api/queue-context` | 0.84–2.34s | 13 wks history + 15 peers |
| `fetch_wfm_context` (WFM deep context) | **0.16s** | was 98.19s before the subquery fix |
| in-band gate (`wfm-not-investigated`) | 0.47–0.60s | no LLM call at all |
| WFM investigation — Groq | 2.4–5.7s | 100k token/DAY cap |
| WFM investigation — NVIDIA | 36.8–67.9s | needs `timeout_seconds` > 100 |
| Default engine — NVIDIA | 36.8–52.5s good, 90–100s slow, occasional hang | ~1 in 3 hangs |
| Deterministic fallback | 2.3–2.6s | no provider reached |
| Per-module smoke test (12 modules) | ~3s | |
| SQL cross-check suite (5 queues, 40 checks) | 3min 11s | includes 40s pacing per case |
| LLM ranking suite (3 queues, 27 checks) | ~3min | NVIDIA, sequential |
| Canary V0.2 session (25 steps) | ~15min | video 14–18MB |
| Canary V0.3 session (18 steps) | ~19min | 3 investigations |

**The number that matters operationally:** an NVIDIA investigation is **45–100s**, and roughly
one call in three hangs regardless of the ceiling. Raising the timeout 100 → 300 was measured and
made it *worse* (same 2/3 success, failure took 5min), so it is set to **150**. Groq is ~10x
faster but its daily quota is easily exhausted.

---

## Session clock log

Wall-clock windows for the sessions on branch `wfm-rca`, all `Asia/Kolkata (IST, UTC+05:30)`.
Anchors are commit timestamps and artifact mtimes.

| Session | Date | Start – End (IST) | What was delivered | Anchor evidence |
|---|---|---|---|---|
| 19 | Tue 28 Jul 2026 | ~19:00 – 20:15 | WFM prompt as an opt-in second engine | test bundle written 19:27 |
| 20 | Tue 28 Jul 2026 | ~21:40 – 22:35 | split into 13 modules; `skeptic` + `correlation_engine` added | `skeptic.py` / `correlation_engine.py` 21:48; `validation-report.json` 22:30 |
| 21 | Tue 28 Jul 2026 | ~22:40 – 23:20 | configurable LLM timeout; LLM ranking 3/3; Canary V0.2 | `llm_client.py` 22:59; `llm-ranking-report.json` 23:13; `wfm-rca-engine.md` 23:15 |
| 22 | Tue 28 – **Wed 29 Jul 2026** | 23:50 – 00:45 | Canary V0.3, `run.bat`, module smoke test, commit + push | Canary V0.3 RCAs 11:50 PM / 11:56 PM (28th); `canary-test-log.md` 00:14; `smoke_test_modules.py` 00:26; `run.bat` 00:40; **commit `254af93` 00:45** |

Total: roughly **5 hours 45 minutes** of working time across the four sessions, spanning the
midnight rollover from 28 to 29 July 2026.

Note the two SQL outages inside that window — `10.10.9.75:1433` went unreachable twice (VPN
drops), once around 19:40 and again around 00:25. Both are visible in the trail as the reason
certain verifications were deferred and re-run.

---

## Session 23 — 2026-07-29 · CQN mapping loaded; the definition conflict resolved
**When:** Wed 29 Jul 2026, ~01:00–02:10 IST · **Runtime:** mapping load <5s; full battery
(12 modules + 40 SQL checks + 27 ranking + 42 spec-clause checks) ~12min end to end.

The client supplied `CQN and FC mapping.xlsx`. Loaded it, and it settled the open question.

1. **Which sheet — measured, not assumed.** Tab order is `Sheet2, Sheet3, Sheet1`, so "the 3rd
   sheet" is the one *named* `Sheet1`. Sheet2 is a count pivot. **Sheet3 is the same mapping in
   PIVOT form with 191 of 523 CQN cells blank** (group labels written once). Forward-fill those and
   Sheet3 and Sheet1 agree on **442/442 names with 0 disagreements**; read naively, Sheet3 maps 167
   names to blank. `--verify-sheets` proves this on demand. Sheet1 is loaded as authoritative
   because it needs no blank-inference and carries the 5 dimension columns needed to join.
2. **Loaded both** — `dbo.CQN_Mapping` (532 rows, Sheet1) and `dbo.CQN_Forecast_Pair` (522 rows,
   Sheet3 Data Pair), indexed, and cross-checked *in SQL*: 0 pairs differ in either direction.
3. **THE CONFLICT IS RESOLVED AND THE SPEC WAS RIGHT.** 35 of 331 Combined Queues span more than
   one channel (`EMEA English ProSupp Client (Multi-Site)` = Case+Chat+Email+Voice over 9
   forecasts). Channel is NOT in the CQN key; the console's `cqnDimsKey` is a locality key, not the
   Combined Queue. The engine now groups channel siblings by the real CQN and reports
   `is_cqn_proxy: false`. Verified live on `Poland Comm Client ProSupport Chat`, whose CQN
   correctly pulls Chat + Email + Voice into one queue — something the locality proxy could not do.
4. **"Unmapped" action item CLOSED — 427/427 queues map, 0 unmapped.**
5. **Language guard added.** A live NVIDIA run put the word "outlier" in the executive summary,
   breaking the prompt's BUSINESS LANGUAGE rule. Asking the model was not enough, so
   `business_report_generator.apply_language_guard()` now rewrites banned statistics vocabulary
   deterministically and logs every rewrite in `language_guard_applied` — visible, not silent.
6. **New suite: `results/spec_compliance_check.py`** — 21 checks mapped clause-by-clause to the
   business prompt (KPI, threshold, top-5 ranking, confidence bands, hypothesis marking, skeptic
   mode, business language, output format, temporal, investigation order, CQN validation,
   correlation, no-fabrication, numeric traceability, actions). **42 PASS / 0 FAIL / 0 SKIP** across
   two providers with SQL up.

**Full battery on this branch, all green:** 12/12 modules · 40/40 SQL cross-checks · 42/42 spec
clauses · LLM ranking 26/27 (the one FAIL is a model-side empty ranking — the engine correctly fell
back rather than ship a causeless report, and the diagnostic now says "proposed nothing").

**Mistake made and fixed:** `json.dump` without `encoding='utf-8'` corrupted the em-dashes in
`selectable_models` labels (they feed the UI picker) into mojibake. Repaired by round-tripping
through cp1252, and the labels render correctly again.

---

## Session 24 — 2026-07-29 · CQN in the UI, mapping integrity proven, multi-model comparison
**When:** Wed 29 Jul 2026, **~09:40 – 11:35 IST** (endpoint + console wiring ~09:40-10:05; Canary
V0.4 10:08-10:16; mapping-integrity analysis 10:25-10:45; multi-model compare 10:50-10:56; Canary
V0.5 10:57-11:10; docs + commit to ~11:35).
**Runtime:** `/api/cqn-mapping` **94ms**; `/api/data` 11,957ms / **44.8MB**; NVIDIA investigations
29-85s; Groq 3.0s; integrity suite ~40s; multi-model compare ~2min; Canary V0.4 6m48s / V0.5 ~12min.

1. **The mapping was in SQL but the CONSOLE could not see it.** `MAP` stayed `null` until someone
   uploaded a file by hand, so every flagged card rendered `unmapped`. Added
   **`GET /api/cqn-mapping`** (serves `dbo.CQN_Mapping`, plus `all_queues` and
   `multi_queue_names`; returns `configured:false` rather than a 500 when the table is absent) and
   wired `rca_console.html` to call it during `sqlFetch`. **First change to the console in this
   branch** — additive; the manual upload path still works.
2. **Zero unmapped, verified three ways** (Canary V0.4 + V0.5): 0 of 250 cards, 0 `.badge.unm` in
   `#qlist`, and no "unmapped" anywhere in `document.body.innerText`. Badge reads
   `CQN mapped from SQL · 442 queues` + a `69 multi-queue` chip.
3. **"Is it 100% mapped?" — answered properly, with a caveat that matters.** New
   `results/cqn_mapping_integrity.py` (6 PASS / 0 FAIL / 4 INFO) separates the senses of the claim:
   coverage is **100% by names (427/427), by rows (66,612) AND by volume (38.9M)**, and — the check
   that goes beyond coverage — the mapping's Region/SubRegion/Channel/Offering **agree with the data
   on 427/427 names**, so it never contradicts the rows it maps.
   **But it is not 1:1:** 69 of 442 names carry more than one Combined Queue, and those names hold
   **41.7% of all demand volume** (16.2M of 38.9M) despite being only 15.7% of rows. Of the 69,
   **23 differ only by a vendor/site suffix** (resolvable by a rule) and **46 are genuinely
   different queues** (needs a business answer). `DB_OSP` differs on only 39, so it cannot
   disambiguate. Current behaviour is the union of a name's queues.
4. **Multi-model comparison.** New `results/multi_model_compare.py` runs one queue through several
   models and diffs the rankings. On `ANZ Comm Client ProSupport` FW202722 — itself one of the 69
   multi-CQN names — **3/3 models answered on the LLM and all three ranked
   `inherited_from_higher_level` first**, `systematic_forecast_bias` second, none shipping an
   unsupported cause. In the UI (Canary V0.5) four models on `NA Core Spanish` FW202719 were
   **unanimous on `genuine demand event`**, diverging only on confidence (60% → 95%).
5. **A monitoring trap found by Canary V0.5:** `POST /api/rca-investigate?provider=groq` returned
   **HTTP 200 in 0.4s** while Groq had 429'd upstream. The backend swallows it by design and returns
   a deterministic payload, so **an LLM outage is invisible to status-code monitoring** — the truth
   is only in `investigation_meta.engine`. Logged in TODO.
6. **`_rcaCurrent` diagnosed more precisely:** it stores an INDEX into `FLAGS`, not a queue key
   (`rca_console.html:2002`). V0.5 saw no drift only because no filter ran between model switches.
7. **MP4 deliverables** — `winget install Gyan.FFmpeg`, then transcode from WebM (Playwright's
   bundled ffmpeg has PNG/VP8 encoders only, no MP4 muxer). V0.4 1.8 MB, V0.5 3.1 MB.

Still unfixed and now seen in four consecutive sessions: the `renderProbe` TypeError on every page
load (`rca_console.html:2117`, from `:2143`) — fallout from `e432543` hiding the Probing layer.

---

## Session 25 — 2026-07-29 · the investigation loop: keep asking WHY until it stops being answerable
**When:** Wed 29 Jul 2026, ~11:50 – 13:05 IST · **Runtime:** the loop is deterministic (<10ms);
a full WFM run is unchanged at 3-5s (Groq) / 30-85s (NVIDIA); regression suites ~14min.

The business pushed back on the output, and the critique was right in a specific, checkable way:
the engine **stopped one level too early**. It reported *"3 of 5 similar queues moved the opposite
way"* and called that a routing shift — a statistical observation, not something a WFM lead can act
on. Their words: *"Business asks 'so what?'"*

**What I verified before agreeing.** Two of their claims held, one did not:
- YES — that phrasing is real: `rca_investigate.py:564`, the DEFAULT engine's deterministic text,
  which is what the console calls. Their screenshot was the old engine, not the WFM one.
- YES — `volume_routing_shift` fired on `peer_divergence.signal` alone: **direction only, no
  conservation test.** An opposite-moving peer was treated as proof that work had moved.
- NO — "the context only has history, peers and stats, so there isn't enough information to
  investigate." **Not true any more.** `channel_siblings` already computed which channel gained,
  which lost, the Combined-Queue total, net vs gross movement and the offset share. The information
  existed; **nothing walked it into a narrative.** That distinction changed the fix from "gather more
  data" to "chain what you already have" — plus one genuine data gap (precedent).

**Built:**
1. **`wfm/investigation_loop.py`** — walks seven investigator questions deterministically, each
   recording its evidence and whether the chain can go deeper: what changed -> local or system-wide
   -> did the Combined-Queue total change or only its distribution -> which channels gained/lost ->
   has this happened before -> what is eliminated -> can a lead act tomorrow. It terminates as
   `operational_cause` or `data_exhausted`, and when it exhausts it **names the data required to go
   deeper** (incident records, campaign calendar, release dates, routing-change history, intraday
   arrivals) instead of inventing a cause.
2. **`cqn_history` in `data_access`** — 26 weeks of whole-Combined-Queue, per-channel totals. This
   was the one real data gap: without it a one-week redistribution and a standing pattern looked
   identical. It answers "has this happened before?" as a frequency rather than a guess.
3. **`volume_routing_shift` now requires CONSERVATION** — either a computed channel redistribution,
   or an opposing peer AND the Combined-Queue total holding flat within 10%. An opposite-moving peer
   is no longer sufficient on its own.
4. **The stopping rule, verbatim as the business wrote it**, plus a WRITE-FOR-THE-INVESTIGATOR
   section that bans "3 of 5 similar queues moved the opposite way" from business-facing text and
   shows the operational rewrite.
5. **`investigation_summary` — the case file** the business reads first: what happened / why / why we
   believe it / what we eliminated / what forecasting should do / how far the investigation got.
   `how_far_the_investigation_got` and `data_required_to_go_deeper` are **always** taken from the
   deterministic loop, never from the model — how far an investigation got is a fact, not an opinion.

**I made the same mistake in my own code, and caught it on the first live run.** Q2 ("system-wide ->
go look at Channel level") **terminated the chain**, so a week where `migration_detected` was already
true never reported the redistribution. My chain stopped at the first plausible explanation — exactly
the critique. Fixed: Q2 is context, not a conclusion; Q3-Q5 now run whenever Combined-Queue data
exists; and Q7 prefers a concrete redistribution over "go up a level".

**Live result** on `SA Comm Client Malaysia ProSupport Email English` FW202722 (-50.7%), all seven
steps, outcome `operational_cause`:

> Q3 Only the distribution — total demand across the Combined Queue barely moved, but the split did.
> Q4 Email +191; Voice -358, Chat -67. This queue's Email went 1,495 -> 1,686.
> Q5 Occasionally — 2 of 25 weeks (8%). Not routine, but it has happened before.
> Q6 Ruled out: holidays, plan change, installed base, standing bias.
> Q7 Forecast the Combined Queue as a whole first and allocate the channel split afterwards; check
>    the routing rules that moved work from Chat and Voice to Email. The forecast was not wrong about
>    total demand — it was wrong about which channel would handle it.

No "3 of 5 similar queues" anywhere in it.

**One more fix from measurement:** the model's `why_we_believe_it` read *"the data suggests a shift in
customer behavior"* while the computed chain had *"Email +191, Voice -358, Chat -67; 2 of 25 weeks"*.
The specifics are the reason to believe it, so the chain is now **appended** to the model's prose
rather than replaced by it.

**Two test failures that were the TEST's fault, not the engine's** — I fixed the tests, not the engine:
- S18 flagged *"if validated, investigate drivers such as product releases, marketing campaigns"* as
  fabrication. That is a **recommendation**, and the stopping rule explicitly asks for it. The check
  now matches the assertion shape ("due to a marketing campaign") rather than any mention.
- S5 required confidence to descend, but the prompt **mandates** `data_quality_issue` rank first,
  which can legitimately outrank confidence (Groq returned 60/65/60). Rank 1 is now exempt when it is
  the mandated data-quality entry.

**Regression: 12/12 modules, 40/40 SQL cross-checks, 42/42 spec clauses.** Example output saved to
`results/investigation-loop-example.json`.

**Not done:** renaming "Root Cause" to "Investigation Summary" in the UI. The field now exists in the
response, but the console still renders the old label — that is a frontend change and a naming
decision, so it is in TODO rather than done unilaterally.
