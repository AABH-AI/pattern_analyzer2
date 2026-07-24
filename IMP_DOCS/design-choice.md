# Design Choices — Demand Pattern RCA Console

Why the tool is built the way it is. Read this before changing metrics, charts, or the parser.

## Guiding constraints (from the client scope)
- **Single self-contained HTML file. No external libraries, no CDN, no build step.** The XLSX reader, CSV/TSV parser, filters, metrics and charts are all hand-rolled so the file runs from `file://` or behind Kong with zero dependencies. Keep it that way — do not add a framework.
- **The engine never invents numbers.** Only two metrics are computed, both rule-based. Every figure shown has an ⓘ that reveals the exact formula and inputs. Any narration/LLM layer (on-prem LLaMA) is a *later* phase and must not compute.

## The two metrics (do not add more without sign-off)
| Metric | Formula | Notes |
|---|---|---|
| **Forecast Accuracy** | `Actual_Offered ÷ fcst_offered × 100` | Forecast = `fcst_offered` (ML). |
| **Forecast Adherence** | `(1 − Actual_Offered ÷ fcst_offered) × 100` — **signed** | **Renamed from "Plan Adherence" and made signed** (session 6): **negative = actual ran above forecast (under-forecast); positive = actual ran below forecast (over-forecast)**. Blank if no actual; the current Excel-system formula. |
- Flag rule: **|Forecast Adherence| > band %** (default ±10). Equivalent to accuracy outside ±band.
- Rows with **no/zero forecast** are data gaps — never scored, never shown as results, counted separately.

## "Avg Accuracy" — the important fix
The old tile averaged `Actual÷Fcst` across rows. Because over- and under-forecasts scatter around 100% and **cancel**, it read ~99% even on genuinely poor data — misleading.
**New definition:** `Avg accuracy = 100 − MAPE`, where MAPE = mean of the per-row absolute % error, which is **exactly |Forecast Adherence|** already computed. Clamped at ≥ 0.
- Ties directly to a metric the business already trusts.
- On the full 138,775-row file this is **77.1%** (vs the bogus ~99%).
- Same logic drives the Dashboard's weekly-accuracy line: `100 − mean(deviation)` per fiscal week.

## Display rules
- `fcst_offered` is surfaced to users as **"forecast offered (Simple)"** and formatted to **2 decimals** everywhere it is shown (report input row, evidence trail, math modal). The **calculation still uses full precision** — only the display is rounded, so formulas never break.
- `Actual_Offered` stays integer; accuracy/adherence stay at 1 dp.

## Filters
10 business dimensions, in this fixed order: Fiscal_Week, Region, SubRegion, Country, Forecast_name, Forecaster, Offering, Projection_plan_name, channel, business_org. Excel-style multi-select with search; "(All)" = no constraint. The same set drives the volumetrics/dashboard (`VOL_DIMS = FILTER_FIELDS`).

## Dashboard & charts — applied the `dataviz` method
- **Form first, colour last.** Trends → area+line; magnitude comparisons → ranked horizontal bars; distribution → labelled status bars.
- **No dual-axis.** Volume and accuracy are two *separate* single-series charts, never two y-scales on one plot.
- **No cycled categorical hues.** Bars use a single sequential **blue** (`--accent`); the deviation spread uses the reserved **status palette** (good/warning/serious/critical) and every band carries a **text label**, so meaning is never colour-alone.
- **Colour matches the app** (`--accent #2d6cdf`, `--accent-2 #12986f`, `--warn`, `--danger`) which sits on the validated blue + status ramps; surfaces are the console's light panels.
- Charts are **inline SVG (trends) / HTML bars** — consistent with the no-library rule. Trends ship a JS **crosshair + tooltip**; bars use native hover titles + direct value labels.
- Everything is **reactive to the active filters** — the dashboard re-renders on every `applyAndScan()`.

### Volumetrics "EPIC" panel — visibility rules
- Dimension cards show **row counts** for the top members, **not % of total** — a share was meaningless for high-cardinality dimensions (325 fiscal weeks ⇒ every value rounded to "0%"). The card's headline is the **distinct-value count** (shown large); bars are scaled relative to the top member within that dimension.
- **Fiscal_Week is excluded** from the dimension grid — it's a time axis already summarised by the KPI hero (span + count) and the two week-trend charts, so a card listing 3 arbitrary weeks was redundant clutter.
- Layout is deliberately roomy: top-3 members per card, larger figures, header dividers, hover lift — tuned for legibility over density.

### Drill-down (one-to-many, card-by-card)
- Every member row in a dimension card is **clickable**. Clicking a value (e.g. Region → EMEA) pushes it onto a **drill path** and re-scopes the *entire* panel — KPIs, all remaining cards, and every chart below — to that subset. Dimensions already on the path are hidden; a **breadcrumb** ("All data › Region: EMEA › …") lets you climb back, and **✕ clear drill** resets.
- The drill is **local to the dashboard** — it does **not** change the RCA Console filters. It re-renders from the last scanned row set (`window._lastRows`) without re-scanning; changing a console filter or band resets the drill.
- Cards show more members when drilled (top 6 vs top 3); **"+N more"** expands the rest in place (scroll-capped at 25). Row counts drive the bars, scaled to the top member of the current scope.
- Implementation: `DRILL[]` state + `drillInto/drillTo/drillClear/drillCrumbs`; clicks handled by one delegated listener on `#dashboardArea` (survives re-renders); members carry `data-df`/`data-dv`, the more-pill carries `data-expand`.

### RCA analytics bundle (signed bias · Actual-vs-Forecast · auto-insights)
- **Actual vs Forecast overlay** (`buildTrend2`) — two series on **one** y-scale (same unit → never a dual-axis): green solid = Σ Actual_Offered/wk, dashed blue = Σ fcst_offered/wk. The visible gap *is* the miss. Shared crosshair shows both + legend.
- **Signed forecast bias** (`divergingBars`) — `Σactual ÷ Σforecast − 1` per member, centred on zero: **right/amber = under-forecast** (actual ran hot), **left/blue = over-forecast** (plan too high). Volume-weighted (sums, not mean-of-ratios) so it's robust. Two charts: by Region (all) and "Most over/under-forecast queues" (top |bias| among **material** queues ≥0.3% of forecast volume, so tiny queues don't dominate). This is the directional signal the old engine lacked.
- **Auto-insights** — rule-based bullets for the current scope (accuracy vs baseline, overall signed bias + direction, worst-mis-forecast queue, largest channel share, flag concentration, data-gap count). No LLM; this is exactly what the on-prem LLaMA layer will later narrate.
- **KPI delta** — when drilled, the Avg-accuracy tile shows ▲/▼ pp vs the un-drilled baseline (`window._lastAcc`), so drilling is comparative.
- All of the above re-scope with the drill path and the console filters, same as the rest of the dashboard.

### Known trade-offs / future polish
- Trend charts plot every fiscal week present (up to 325 points); fine as a dense sparkline. A brush/zoom is a future nice-to-have.
- Full crosshair is on the two trend charts only; bars rely on native tooltips. A shared hover legend is a later enhancement.

## Full pipeline: data ingestion → RCA (live SQL)
- A **pipeline strip** at the top of the RCA Console visualises the end-to-end path and fills as data flows: **Source → Ingest (rows) → Compute · 2 metrics (scored) → Flag · ±band (flagged) → RCA (ready)**. It's always visible (pending state before load) so the demo tells the whole story at a glance.
- **"🗄 Connect to SQL Server (AA)"** button + modal (Server / Database / Table = `10.10.9.75` · `Playground` · `dbo.Input_To_ML`). **Now live** (Timeline P6 done): **Fetch table** calls the local **FastAPI + pyODBC** backend (`backend/sql_backend.py`, `GET /api/data`) which runs `SELECT * FROM <table>` and returns JSON; `sqlFetch` loads it straight into the pipeline — no upload. Connection details live in `backend/config.json` or `SQL_*` env vars (both gitignored). The full **138,775-row** table is loaded into `Playground.dbo.Input_To_ML` by `backend/upload_excel_to_sql.py`. Always-on hosting (internal server) is packaged in `DEPLOY.md` (Docker/service). Setup + troubleshooting: `IMP_DOCS/installation-and-connection.md`. Browsers can't reach SQL directly — the backend is the bridge; a public static host (GitHub Pages) therefore can't use SQL, by design.
- Source tracking: `window._pendingSrc` ('sql' via the modal, 'file' via Upload) → `window.SRC`, read in `onWeekly`; `renderPipe()` is called on load (pending), on ingest, and after each scan.
- **Evidence trail removed** from the RCA report (was redundant with the Findings bullets + the ⓘ formula/number modal, which remain the source of the math). The report is now: Findings (with ⓘ) → Inputs used.

## Session-6 merge (`shivam-updates` → main) — dashboard refinements
Merged clean (merge commit `babf5a1`); both feature sets kept. Shivam's additions:
- **"Plan Adherence" renamed to "Forecast Adherence"** and made **signed** (was `ABS(...)`). Sign shows direction: **− = actual above forecast (under-forecast), + = actual below forecast (over-forecast)**. Flag is now on the **absolute** value, `|Forecast Adherence| > band` — same threshold behaviour as before.
- **Deviation colour-bands** on the dashboard (good/warn/serious/critical) + a **flagged-% KPI**.
- **Right-side Insights drawer** — the scope-aware rule-based callouts moved into a slide-in panel.
- **Agentic deep-dive / exploration-trace UI** — a step-by-step "how the agent would explore this miss" trace (presentation of reasoning; still rule-based, computes nothing new).
- **Definitions & Formulas tab** updated to the signed formula + deviation-spread bands.
> Note: a couple of legacy "Plan Adherence" strings remain in the UI (a notes-card line and a code comment) — cosmetic; the computed metric and its ⓘ modal are "Forecast Adherence".

## Sessions 7–11 — dashboard filters, Fiscal-Week popup, run tooling, data scope
- **Dashboard dropdown filters** (Region, Sub-Region, Country, Channel, Offering, Forecaster, Projection plan) drive the same scan engine, so the graphs recompute the affected/flagged queues for the selection.
- **Fiscal Week — typeable (Excel-style)**: a datalist type-ahead over all weeks; accepts exact / partial (`2024`) / comma list / range (`202401-202410`).
- **Affected-queues popup**: selecting a Fiscal Week (Enter / pick) opens a modal listing the **real flagged forecast names** for that week (name · week · signed adherence · band · direction), straight from `FLAGS` — no fabrication. An **ⓘ** button explains it.
- **"Forecast names by adherence band" chart**: every name bucketed by its worst week's |Forecast Adherence| into ≤±5 / ±5–10 / ±10–15 / ±15–20 / ±20–25 / >±25 (companion to the all-weeks spread).
- **Data-ingestion loading screen**: a 6-step overlay (read → parse → build → compute → flag → render) on both the file and SQL paths.
- **Run tooling**: `run.ps1` / `run.sh` one-command setup+run; `AGENTS.md` + `CLAUDE.md` so any AI/human can install and run (SQL included).
- **Data scope**: truncated to **FY2025–2027 (66,612 rows)**; the loader keeps it truncated on reload.

## SQL table & data types (`Playground.dbo.Input_To_ML`)
Loaded from the weekly Excel by `backend/upload_excel_to_sql.py`. **33 columns · 66,612 rows** (Fiscal_Week **202501–202752 = FY2025–2027**; 2022–2024 and 2028–2029 were truncated). The loader persists this cut via a Fiscal_Week range filter — config `min_fiscal_week`/`max_fiscal_week` (202500–202799) or `--min-week`/`--max-week`; remove them to load all years.
- `Fiscal_Week` — **BIGINT** · `Week_Ending` — **DATE**
- **Dimensions (NVARCHAR):** Region, SubRegion, Country, Forecast_name, Forecaster, Offering, Projection_plan_name, channel, business_org, Volume_Category
- **Measures (FLOAT):** Actual_Offered, Actual_Handled, fcst_offered, fcst_handled, Planned_ASU, Actual_ASU, Final_Units, Final_Y5…Final_Y1, Final_upp_units, Holiday_Count, Monday…Sunday

Blank cells load as **NULL**. The two metrics only need `Actual_Offered` and `fcst_offered`; the rest are dimensions/context for filtering and volumetrics. Column typing lives in `upload_excel_to_sql.py` (`NUMERIC` / `INT_COLS` / `DATE_COLS` sets); unknown columns default to `NVARCHAR(255)`.

## Timeline / Gantt
The build Gantt lives both **in the app** (Timeline tab, scoped under `#tab-timeline`) and as a **standalone** `rca_timeline.html` (theme-aware light/dark). Keep the two in sync when phase status changes. Today marker and KPIs are currently hard-set to **22 Jul** — update them as the project moves.
