# Handoff — Demand Pattern RCA Console

Everything a new dev (or future-you) needs to continue. Deploy target: **30 Jul 2026** (last dev day 29th).

## What this is
A single-file, dependency-free HTML tool ("Demand Pattern RCA Agent — Console") that ingests the weekly demand file in-browser and produces rule-based RCA on two metrics. It is the **mockup deliverable** for the enterprise Agentic-Platform RCA agent (LangGraph + on-prem LLaMA + MCP tools); the tabs after "Timeline" document that target architecture.

## Files in this folder
| File | Purpose |
|---|---|
| `rca_console.html` | **The app.** Open in any modern browser (Chrome/Edge). Everything is inline. |
| `rca_timeline.html` | Standalone build Gantt to 30 Jul (theme-aware). Mirrors the in-app Timeline tab. |
| `IMP_DOCS/` | This documentation set — see `rca-investigation-contract.md` for the RCA feature's exact request/response shape. |
| `backend/` | FastAPI + pyODBC SQL connector (`sql_backend.py`, `/api/data`) + Excel→SQL loader (`upload_excel_to_sql.py`) + the Root-Cause Investigation engine + proxy (`rca_investigate.py` via `/api/rca-investigate`, `/api/models`). Powers live SQL and the RCA Investigation feature. |
| `DEPLOY.md` · `docker-compose.yml` · `backend/Dockerfile` | Always-on internal-server hosting (Docker / Windows-service / systemd). |
| `run.ps1` · `run.sh` | One-command setup + run (installs deps, seeds config, starts backend). |
| `AGENTS.md` · `CLAUDE.md` | Runbook for any AI/human — what it is, run paths, SQL setup, guardrails. |

> The Excel input (`Input_To_ML_*.xlsx`) is intentionally **not** in this folder. Point the tool at your own copy via the upload button.

## Running it
1. Double-click `rca_console.html` (or serve behind Kong).
2. **RCA Console** tab → *Upload weekly file* → pick the `.xlsx`/`.csv`. (Optional: *Upload CQN mapping* to resolve queue names.)
3. Filter like Excel (10 dimensions) or type 2–3 `Forecast_name`s in the test box.
4. Click a flagged item → RCA report with ⓘ math, then **🔎 Investigate Root Cause** → the full investigation report (needs the backend running for a real/placeholder response — see below; without it you get a clear "start the backend" error, not a crash). **Dashboard** tab → volumetrics + graphs (follows your filters). **Timeline** tab → deadline Gantt.

**Live SQL (backend):** `cd backend && pip install -r requirements.txt`, create `config.json` from `config.example.json` (server `10.10.9.75`, db `Playground`, table `dbo.Input_To_ML`, your SQL login), `uvicorn sql_backend:app --port 8000`, open `http://localhost:8000/rca_console.html` → **Connect to SQL Server (AA)**. Full steps, Docker, and troubleshooting: `IMP_DOCS/installation-and-connection.md`.

## Code map (inside `rca_console.html`, one `<script>`)
- **Parsing:** `fileToArrays` → `parseXlsx` (hand-rolled ZIP+XML reader) / `parseDelimited`; `buildRows` maps header→row objects.
- **Filters:** `FILTER_FIELDS` (10 dims) → `buildFilters`, `passFilters`, `toggleAll/Opt`.
- **Scan:** `applyAndScan` computes `_ao/_fo/_acc/_padh/_noF` per row (Plan-Adherence is **signed**, see design-choice.md), groups by Forecast_name, builds `FLAGS`.
- **Metrics:** `setAccuracy` (= 100 − MAPE, uses `Math.abs()` explicitly since `_padh` is signed), `renderMetrics`.
- **Dashboard:** `renderDashboard` (aggregates in one pass) + chart primitives `htmlBars`, `buildTrend`, `wireTrends`.
- **Report:** `buildFindings`, `selectFlag`, `showMath` (modal).
- **Root-Cause Investigation** (replaces the earlier rule-based RCA panel — removed): `triggerRCA` (Trigger) → `aggregateData`/`buildContext`/`buildStatSummary` (Data Aggregator + Context Builder, fully generic — no hardcoded field list) → `callInvestigationEngine` (POSTs to `backend/rca_investigate.py` via `sql_backend.py`'s `/api/rca-investigate`) → `formatInvestigation` (Formatter) → `renderInvestigationReport` (Renderer). See `IMP_DOCS/rca-investigation-contract.md` for the exact contract.
- **Probing:** `PROBES` (static) + `renderContextProbes` (data-driven) + `saveKnowledge`/`downloadKB` (Markdown export, localStorage-backed).
- **SQL connect:** `sqlFetch` now calls the backend `GET /api/data` and loads rows straight into the pipeline (was a file-picker mock); `renderPipe` marks Source = "SQL Server (AA)". Backend: `backend/sql_backend.py`.

## How to verify a change (no test runner needed)
1. Syntax: extract the script and `node --check`.
2. Logic: a DOM-stub Node harness can `eval` the script, set `ROWS`, call `buildFilters()`+`applyAndScan()` and assert on the produced HTML. For the RCA Investigation flow, stub `global.fetch` to return a canned `InvestigationResponse` and call `triggerRCA(i)` — no live backend needed to verify the client-side pipeline.
3. Visual: `chrome --headless=new --screenshot` against a temp HTML that injects sample rows and activates the target tab.
4. Backend: `python -c "import py_compile; py_compile.compile('sql_backend.py', doraise=True)"` (and `rca_investigate.py`), plus a direct call to `investigate({...}, {})` to confirm the placeholder response shape.

## State of play (2026-07-27)
- **Merged `main` into `shivam-updates`** (this merge): brings main's dashboard filters, typeable Fiscal-Week field + affected-queues popup, 10-step timeline, FY2025–2027 data truncation, and run tooling (`run.ps1`/`run.sh`, `AGENTS.md`/`CLAUDE.md`) together with the RCA-engine work below.
- **RCA Investigation is now LIVE (no longer a placeholder):** `backend/rca_investigate.py` calls a real LLM (NVIDIA + Groq, OpenAI-compatible) with two deterministic passes around it — `derive_features()` (field hygiene + discriminating per-queue features) and `_verify_and_fix()` / `_fill_gaps()` (reject circular "the miss is the cause" answers, and fill every report section). Output is **plain business language**; **Key Findings / Root Cause / Reasoning** are distinct; a **per-queue model picker** (`/api/models`, default `nvidia/nemotron-3-super-120b-a12b`) lets leads compare models. Details: design-choice.md "RCA engine v2".
- **Timeline** is now **10 steps** (added "RCA output — report per queue"); the build Gantt **auto-sets "today" from the PC clock** and is light-only.
- **Dashboard** gained: dropdown filters + a **typeable Excel-style Fiscal Week** field; an **affected-queues popup** (real flagged names for the selected week) with an **ⓘ** hint; a **"Forecast names by adherence band"** chart (≤±5…>±25); a **6-step data-ingestion loading screen**; plus our deviation colour-bands, flagged-% KPI, and right-side **Insights drawer**.
- **Data scope** — the live table is now `dbo.Input_To_ML_Full_138_Trimmed`: 114,436 rows, 32 columns, FW202401–FW202908. The FY2025–2027 truncation to 66,612 rows described below applied to the earlier `dbo.Input_To_ML`; the loader keeps it truncated via a Fiscal_Week range filter (`min/max_fiscal_week`, CLI `--min-week/--max-week`).
- **SQL is live:** FastAPI + pyODBC backend (`backend/`) queries SQL Server; "Connect to SQL Server (AA)" pulls via `GET /api/data`. Table `Playground.dbo.Input_To_ML` on `10.10.9.75` (**66,612 rows, FY2025–2027**). Hosting packaged (Docker / Windows-service / systemd) — see `DEPLOY.md`, `IMP_DOCS/installation-and-connection.md`.
- **In progress:** P4 — multi-queue scan → top-N → **printable Phase-1 digest** (main remaining build).
- **To do:** SME validation with Prashant + band tuning (±10 vs ±15 — note ~66% flag rate); demo packaging + dry run; presentation.

## State of play (2026-07-29) — branch `wfm-rca`

Pushed as **`wfm-rca`** (commit `254af93`), deliberately kept separate: `main`,
`shivam-updates` and `call2` are all untouched by it.

- **A SECOND RCA engine, opt-in per request.** `POST /api/rca-investigate?mode=wfm` runs the
  business-authored WFM specification from `backend/wfm/` (13 modules). Omit `mode` and the
  endpoint behaves exactly as before. `rca_console.html` is **unmodified** — the WFM engine
  backfills every legacy response key, so the current UI renders its output as-is.
  Contract, module map and known gaps: `wfm-rca-engine.md`.
- **Two modules close real gaps in the spec.** `skeptic.py` gates all 10 cause types on a feature
  precondition, so a verdict the data cannot support (e.g. `plan_restatement` on a week the plan
  did not change) is *rejected* rather than published; it also reconciles every cited figure
  against the source data. `correlation_engine.py` computes the driver relationships the prompt
  asked for but nothing provided, plus the **exact ASU decomposition** — verified identity-exact
  on all 22,003 flagged misses carrying both ASU columns.
- **A data-quality gate was added** (not in the spec, implied by it): an isolated extreme that
  reverts immediately is ranked as a *suspected data issue to validate at source*, never explained
  as a business event. This **revises Session 15's conclusion** on `NA Core Spanish` FW202719
  (actual 8,805 vs ~117 typical) — that figure is probably a decimal-shift ingestion error, not a
  demand event. **It should be validated at source.**
- **`llm.timeout_seconds`** in `config.json` now drives the LLM read timeout for *both* engines
  (150; the original hard-coded 100 remains the fallback when the key is absent).
- **`run.bat`** — one-shot Windows runner: deps, config, VPN (Cisco Secure Client), SQL
  reachability, port, backend + health wait, optional test suites, browser.
- **Evidence lives in `results/`** — start with `results/audit-log.md`. 40/40 SQL cross-checks over
  5 deliberately-chosen queues, 3/3 queues answered by the LLM with 27/27 ranking checks, 12/12
  per-module smoke tests, and two recorded browser sessions.
- **Known open items** (all in `TODO.md`): ranking **correctness** is still unmeasured and needs a
  labelled set — everything verified so far is internal consistency, not truth; ~1 in 3 NVIDIA
  calls hangs and a bigger timeout makes it worse, not better; the **CQN definition conflicts with
  the spec** (the console's signed-off CQN includes channel, the spec wants migration *within* a
  CQN across channels) so migration runs on a clearly-labelled proxy and needs a business answer;
  and Canary found UI defects incl. a load-time `TypeError` on every page load and flagged-queue
  cards that may not be clickable by a real pointer.

## Watch-outs
- Keep the **console** library-free. No CDN (must run behind Kong / offline). The backend is a separate, optional Python service — that boundary is intentional (see `IMP_DOCS/rca-investigation-contract.md`), don't blur it by adding libraries to `rca_console.html` itself.
- **Never change the two formulas' math** — only display/rounding. The ⓘ modal must always match what's computed. Forecast Adherence is now **signed** — any code touching `_padh` for flagging/severity/sorting/MAPE must compare on `Math.abs()`, only the *displayed* number stays signed.
- **The RCA Investigation Engine must never fabricate a conclusion.** If no provider is configured (or a call fails), show the honest placeholder/error — never synthesize a plausible-looking root cause client-side to "fill the gap."
- When phase status changes, update **both** the Timeline tab and `rca_timeline.html` (and the "today" marker/KPIs).
- WSL note (this workstation): browsers here can't reach localhost dev servers — QA static files via `file://` + headless screenshots, not a loopback server.
- **`?mode=wfm` is additive and must stay that way.** The default path is what the console uses in
  production; never change its behaviour to serve the WFM engine. Both are exercised by
  `results/run_validation.py` (which asserts the default path leaks no WFM keys).
- **Do not "fix" a deterministic fallback by removing the guard.** `wfm-deterministic-fallback` and
  `deterministic-fallback` are correct, honest outcomes when a provider is unreachable — the reason
  is always recorded in `missing_information`. Read it before assuming the engine is broken.
