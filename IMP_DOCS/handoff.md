# Handoff — Demand Pattern RCA Console

Everything a new dev (or future-you) needs to continue. Deploy target: **30 Jul 2026** (last dev day 29th).

## What this is
A single-file, dependency-free HTML tool ("Demand Pattern RCA Agent — Console") that ingests the weekly demand file in-browser and produces rule-based RCA on two metrics. It is the **mockup deliverable** for the enterprise Agentic-Platform RCA agent (LangGraph + on-prem LLaMA + MCP tools); the tabs after "Timeline" document that target architecture.

## Files in this folder
| File | Purpose |
|---|---|
| `rca_console.html` | **The app.** Open in any modern browser (Chrome/Edge). Everything is inline. |
| `rca_timeline.html` | Standalone build Gantt to 30 Jul (theme-aware). Mirrors the in-app Timeline tab. |
| `IMP_DOCS/` | This documentation set. |

> The Excel input (`Input_To_ML_*.xlsx`) is intentionally **not** in this folder. Point the tool at your own copy via the upload button.

## Running it
1. Double-click `rca_console.html` (or serve behind Kong).
2. **RCA Console** tab → *Upload weekly file* → pick the `.xlsx`/`.csv`. (Optional: *Upload CQN mapping* to resolve queue names.)
3. Filter like Excel (10 dimensions) or type 2–3 `Forecast_name`s in the test box.
4. Click a flagged item → RCA report with ⓘ math. **Dashboard** tab → volumetrics + graphs (follows your filters). **Timeline** tab → deadline Gantt.

## Code map (inside `rca_console.html`, one `<script>`)
- **Parsing:** `fileToArrays` → `parseXlsx` (hand-rolled ZIP+XML reader) / `parseDelimited`; `buildRows` maps header→row objects.
- **Filters:** `FILTER_FIELDS` (10 dims) → `buildFilters`, `passFilters`, `toggleAll/Opt`.
- **Scan:** `applyAndScan` computes `_ao/_fo/_acc/_padh/_noF` per row, groups by Forecast_name, builds `FLAGS`.
- **Metrics:** `setAccuracy` (= 100 − MAPE), `renderMetrics`.
- **Dashboard:** `renderDashboard` (aggregates in one pass) + chart primitives `htmlBars`, `buildTrend`, `wireTrends`.
- **Report:** `buildFindings`, `selectFlag`, `showMath` (modal).
- **Probing:** `PROBES` (static) + `renderContextProbes` (data-driven) + `saveKnowledge`/`downloadKB` (Markdown export, localStorage-backed).

## How to verify a change (no test runner needed)
1. Syntax: extract the script and `node --check`.
2. Logic: a DOM-stub Node harness can `eval` the script, set `ROWS`, call `buildFilters()`+`applyAndScan()` and assert on the produced HTML — see `prompt-trail.md` for the pattern.
3. Visual: `chrome --headless=new --screenshot` against a temp HTML that injects sample rows and activates the target tab.

## State of play (2026-07-22)
- **Done & verified:** schema lock, two-metric engine (calc fixed), file ingestion, volume metrics + Dashboard + evidence trail.
- **In progress:** P4 — multi-queue scan → top-N → **printable Phase-1 digest** (main remaining build).
- **To do:** P6 validation with Prashant/SME + band tuning; P7 demo packaging + dry run; P8 presentation (30 Jul).

## Watch-outs
- Keep it **library-free**. No CDN (must run behind Kong / offline).
- **Never change the two formulas' math** — only display/rounding. The ⓘ modal must always match what's computed.
- When phase status changes, update **both** the Timeline tab and `rca_timeline.html` (and the "today" marker/KPIs).
- WSL note (this workstation): browsers here can't reach localhost dev servers — QA static files via `file://` + headless screenshots, not a loopback server.
