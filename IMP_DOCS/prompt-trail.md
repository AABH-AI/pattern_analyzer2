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

## Session 3 — 2026-07-22/23 · Dashboard RCA analytics + live SQL groundwork
Requested → delivered:
1. **Drillable volumetrics** — one-to-many card-by-card drill with breadcrumb + expandable members.
2. **Dashboard RCA bundle** — Actual-vs-Forecast weekly overlay (one y-scale), signed forecast bias, auto-insights, drill KPI delta.
3. **"🗄 Connect to SQL Server (AA)"** groundwork — connect modal + pipeline strip (Source → Ingest → Compute → Flag → RCA); dropped the redundant evidence trail.
4. Stopped tracking the KB export; added `.gitignore` (excludes KB + input data).

## Session 4 — 2026-07-24 · Definitions/Formulas + Dashboard polish (Claude)
**Branch:** created `shivam-updates` (personal working branch off `main`); merged `origin/main` repeatedly to stay current.
Requested → delivered:
1. **Definitions & Formulas tab** — deviation-spread rebucketed to 5 bands (±5 / ±10 / ±15–20 / ±20–25 / >±25); round brackets added to Forecast Accuracy; **Plan Adherence (ML/Manual) renamed → Forecast Adherence**; field-definitions table replaced with all 34 source columns (Monday–Sunday collapsed to one row).
2. **Deviation-band colours** → blue / green / orange / amber / red.
3. **Top flagged forecast names** — total flagged weeks in the corner + per-bar % share.
4. **Insights** moved out of the dashboard flow into a **slidable, resizable right-side drawer** (open by default on Dashboard); dashboard reserves layout space (`body` padding) so it reflows rather than being overlaid; 7 KPI hero cards fit on a single row.
5. Labelled the mystery focus-clear button (`✕` → `✕ Clear`).
Verification: `node --check` after every change.

## Session 5 — 2026-07-24 · Root-Cause Investigation rebuild (LLM-driven)
Requested → delivered (see `TODO.md` "Done ✓ (2026-07-24…)" and `rca-investigation-contract.md` for full detail):
1. **Removed** the earlier rule-based "agentic exploration" RCA panel per client instruction — replaced with a genuine LLM-investigation architecture (a rules engine dressed as AI reasoning would violate the client's own "never fabricate" principle).
2. **Signed Plan Adherence** — `ABS` removed from the formula and every display; flagging/severity/sort/MAPE still compare on `Math.abs()`, only the displayed number is signed.
3. **Six-module architecture** (client spec §7): RCA Trigger, Data Aggregator, Context Builder, LLM Investigation Engine, RCA Formatter, UI Renderer — Aggregator/Context fully generic (no hardcoded field list; auto-discovered `Final_upp_units` in testing).
4. Backend proxy `POST /api/rca-investigate` (`backend/rca_investigate.py` + `sql_backend.py`) so provider keys stay server-side; **honest placeholder** response until a provider is wired.
5. **Adversarial spec-compliance review** (4 reviewers + adjudication). Found & fixed a pre-existing **CRITICAL** hole: the static mount served `GET /backend/config.json` (live SQL creds in plain text) — now blocked by middleware. ⚠️ Predated this feature and was exploitable in production — flagged for credential rotation.

## Session 6 — 2026-07-24 · Live LLM wiring + SQL-scoped RCA
Requested → delivered:
1. **Groq + NVIDIA wired** (OpenAI-compatible), automatic fallback chain → honest placeholder; `forecast_summary` always from our own deterministic numbers, never the model's echo.
2. Live-verified against the real internal SQL Server on real flagged queues; fixed a Cloudflare-403 (User-Agent), a real **413 token-limit** payload bug (slimmed history/peers to `{key,computed}`, caps `RCA_HISTORY_CAP=12`/`RCA_PEERS_CAP=15`, 413-retry), and a fixed-position env-var override bug during the NVIDIA-primary/Groq-secondary swap.
3. Added `GET /api/queue-context` — scoped, parameterized SQL query (target row + history + CQN peers) instead of client-side filtering the whole table.
4. ⚠️ Caught real API keys briefly pasted into `config.example.json` (the committed template) — removed before staging; confirmed absent from index/history. Reminder: secrets go only in `config.json`/`.env`, never `.example` files.

## Session 7 — 2026-07-24 · Browse-any-queue + backend setup fix (Claude)
Requested → delivered:
1. **Backend setup fix** — "Connect to SQL Server" failed with `No module named 'pyodbc'` on this machine (worked on a teammate's). Diagnosed: ODBC Driver 17 present, `pyodbc` missing; installed `pyodbc-5.3.0`; live-verified a real connection returning **138,775 rows**. Per-machine setup gap, not a code bug.
2. **Browse any queue without code changes** — `<datalist>` autocomplete of every distinct `Forecast_name`; **🎲 Random queue** button; `triggerRCA` offers **"🔎 Investigate anyway"** (`force=true`) for a deliberately-picked non-flagged queue (automatic path still gated on a real miss).
3. Doc maintenance — brought `prompt-trail.md` up to date; `design-choice.md`/`handoff.md`/`TODO.md` updated alongside the feature work.
