# Handoff — Demand Pattern RCA Console

Everything a new dev (or future-you) needs to continue. Deploy target: **30 Jul 2026** (last dev day 29th).

## What this is
A single-file, dependency-free HTML tool ("Demand Pattern RCA Agent — Console") that ingests the weekly demand file in-browser and produces rule-based RCA on two metrics. It is the **mockup deliverable** for the enterprise Agentic-Platform RCA agent (LangGraph + on-prem LLaMA + MCP tools); the tabs after "Timeline" document that target architecture.

## Files in this folder
| File | Purpose |
|---|---|
| `rca_console.html` | **The app.** Open in any modern browser (Chrome/Edge). Everything is inline. |
| `rca_timeline.html` | Standalone build Gantt to 30 Jul (theme-aware). Mirrors the in-app Timeline tab. |
| `backend/` | FastAPI service: SQL Server connector (`/api/data`) + the Root-Cause Investigation proxy (`/api/rca-investigate`, see below). Optional for everything except live SQL and the RCA Investigation feature. |
| `IMP_DOCS/` | This documentation set — see `rca-investigation-contract.md` for the RCA feature's exact request/response shape. |

> The Excel input (`Input_To_ML_*.xlsx`) is intentionally **not** in this folder. Point the tool at your own copy via the upload button.

## Running it
1. Double-click `rca_console.html` (or serve behind Kong).
2. **RCA Console** tab → *Upload weekly file* → pick the `.xlsx`/`.csv`. (Optional: *Upload CQN mapping* to resolve queue names.)
3. Filter like Excel (10 dimensions) or type 2–3 `Forecast_name`s in the test box.
4. Click a flagged item → RCA report with ⓘ math, then **🔎 Investigate Root Cause** → the full investigation report (needs the backend running for a real/placeholder response — see below; without it you get a clear "start the backend" error, not a crash). **Dashboard** tab → volumetrics + graphs (follows your filters). **Timeline** tab → deadline Gantt.

## Code map (inside `rca_console.html`, one `<script>`)
- **Parsing:** `fileToArrays` → `parseXlsx` (hand-rolled ZIP+XML reader) / `parseDelimited`; `buildRows` maps header→row objects.
- **Filters:** `FILTER_FIELDS` (10 dims) → `buildFilters`, `passFilters`, `toggleAll/Opt`.
- **Scan:** `applyAndScan` computes `_ao/_fo/_acc/_padh/_noF` per row (Plan-Adherence is **signed**, see design-choice.md), groups by Forecast_name, builds `FLAGS`.
- **Metrics:** `setAccuracy` (= 100 − MAPE, uses `Math.abs()` explicitly since `_padh` is signed), `renderMetrics`.
- **Dashboard:** `renderDashboard` (aggregates in one pass) + chart primitives `htmlBars`, `buildTrend`, `wireTrends`.
- **Report:** `buildFindings`, `selectFlag`, `showMath` (modal).
- **Root-Cause Investigation** (replaces the earlier rule-based RCA panel — removed): `triggerRCA` (Trigger) → `aggregateData`/`buildContext`/`buildStatSummary` (Data Aggregator + Context Builder, fully generic — no hardcoded field list) → `callInvestigationEngine` (POSTs to `backend/rca_investigate.py` via `sql_backend.py`'s `/api/rca-investigate`) → `formatInvestigation` (Formatter) → `renderInvestigationReport` (Renderer). See `IMP_DOCS/rca-investigation-contract.md` for the exact contract.
- **Probing:** `PROBES` (static) + `renderContextProbes` (data-driven) + `saveKnowledge`/`downloadKB` (Markdown export, localStorage-backed).

## How to verify a change (no test runner needed)
1. Syntax: extract the script and `node --check`.
2. Logic: a DOM-stub Node harness can `eval` the script, set `ROWS`, call `buildFilters()`+`applyAndScan()` and assert on the produced HTML. For the RCA Investigation flow, stub `global.fetch` to return a canned `InvestigationResponse` and call `triggerRCA(i)` — no live backend needed to verify the client-side pipeline.
3. Visual: `chrome --headless=new --screenshot` against a temp HTML that injects sample rows and activates the target tab.
4. Backend: `python -c "import py_compile; py_compile.compile('sql_backend.py', doraise=True)"` (and `rca_investigate.py`), plus a direct call to `investigate({...}, {})` to confirm the placeholder response shape.

## State of play (2026-07-24)
- **Done & verified:** schema lock, two-metric engine (signed Plan Adherence), file ingestion, volume metrics + Dashboard, live SQL Server backend + Docker deployment, **Root-Cause Investigation** architecture (Trigger/Aggregator/Context Builder/Formatter/Renderer all real and tested; LLM Investigation Engine is an honest placeholder — no provider connected yet).
- **In progress:** P4 — multi-queue scan → top-N → **printable Phase-1 digest** (main remaining build).
- **To do:** wire a real LLM provider in `backend/rca_investigate.py` (`call_model()`) when one is chosen; P6 validation with Prashant/SME + band tuning; P7 demo packaging + dry run; P8 presentation (30 Jul).

## Watch-outs
- Keep the **console** library-free. No CDN (must run behind Kong / offline). The backend is a separate, optional Python service — that boundary is intentional (see `IMP_DOCS/rca-investigation-contract.md`), don't blur it by adding libraries to `rca_console.html` itself.
- **Never change the two formulas' math** — only display/rounding. The ⓘ modal must always match what's computed. Plan Adherence is now **signed** — any code touching `_padh` for flagging/severity/sorting/MAPE must compare on `Math.abs()`, only the *displayed* number stays signed.
- **The RCA Investigation Engine must never fabricate a conclusion.** If no provider is configured (or a call fails), show the honest placeholder/error — never synthesize a plausible-looking root cause client-side to "fill the gap."
- When phase status changes, update **both** the Timeline tab and `rca_timeline.html` (and the "today" marker/KPIs).
- WSL note (this workstation): browsers here can't reach localhost dev servers — QA static files via `file://` + headless screenshots, not a loopback server.
