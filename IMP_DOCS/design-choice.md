# Design Choices — Demand Pattern RCA Console

> **As of 2026-08-14. This document is a record, not a current-state reference.**
> A record of DECISIONS and why they were taken, in the order they were taken. The data facts quoted alongside each decision -- 33 columns, 138,775 and 66,612 rows, dbo.Input_To_ML -- were true at that time and are deliberately not rewritten, since the reasoning only makes sense against the data the decision was made on.
>
> For what is true NOW: the live table and port are in `backend/config.json` and `IMP_DOCS/installation-and-connection.md`; current engine behaviour is in `IMP_DOCS/new-prompt-conformance.md`, `prompt2-conformance.md` and `holiday-semantic-groups.md`.

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
- Severity/sort/MAPE (100−MAPE accuracy) all compare on `Math.abs(deviation)` — only the *displayed* number is signed; see `applyAndScan`/`setAccuracy` comments in `rca_console.html`.

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
- **Evidence trail removed** from the RCA report (was redundant with the Findings bullets + the ⓘ formula/number modal, which remain the source of the math). The report is now: Findings (with ⓘ) → Inputs used → **Root-Cause Investigation** (below).

## Root-Cause Investigation — LLM-driven, replaces the earlier rule-based RCA panel
A prior session built a rule-based "agentic exploration" RCA panel (trend/sibling/discovery-lift/memory, all deterministic JS). **That panel was removed entirely** per client instruction — the client's spec requires the LLM to genuinely reason over the data (generate hypotheses, weigh evidence for/against, reject the unsupported, rank what's left, state confidence and missing information) rather than follow any fixed checklist, deterministic or otherwise. Faking that with rule-based JS presented as "AI reasoning" would violate the client's own design principle: *never fabricate evidence, explicitly state uncertainty.*

**Architecture (matches the client's spec section 7 verbatim), each piece independently testable:**
1. **RCA Trigger** (`triggerRCA`, client-side) — re-validates the row is outside the configured band, then sequences the rest.
2. **Data Aggregator** (`aggregateData`, client-side) — captures the target row's **entire raw field set** generically (`Object.keys(r)` minus our internal `_`-prefixed computed fields — no hardcoded column list), plus prior weeks for the same `Forecast_name` (capped at `RCA_HISTORY_CAP=13` — the prior weeks used both for the "usual" comparisons and sent to the model) and same-week peers sharing the CQN dims (Region/SubRegion/Country/Channel), different `Forecast_name`.
3. **Context Builder** (`buildStatSummary`/`buildContext`, client-side) — for **every field discovered** across target ∪ history (again, no hardcoded list — verified in testing that a column never referenced by name, `Final_upp_units`, was auto-included), computes generic stats: numeric fields get history mean/stdev/z-score/outlier flag (\|z\|>2, a standard statistical convention, not an invented business threshold)/trend slope; categorical fields get changed-vs-prior + distinct recent values.
4. **LLM Investigation Engine** — the only module allowed to decide a cause. Lives **server-side** in `backend/rca_investigate.py` (proxied via `POST /api/rca-investigate` in `sql_backend.py`) so a real provider key never has to sit in the publicly-hosted `rca_console.html`. **No provider is wired yet** — `investigate()` returns an honest placeholder (empty root-cause/hypotheses, not a fabricated one) until `llm.provider` is configured and `call_model()` is implemented. See `IMP_DOCS/rca-investigation-contract.md` for the exact request/response shape.
5. **RCA Formatter** (`formatInvestigation`, client-side) — display formatting + safe fallbacks only; invents no content.
6. **UI Renderer** (`renderInvestigationReport`, client-side) — the investigation-report layout: Forecast Summary, Key Findings, Root Causes (with confidence bar + evidence chips), Supporting Evidence, Rejected Hypotheses, Historical Comparison, Reasoning Narrative, Forecast Improvement Recommendations, Confidence, Missing Information. Collapsible via native `<details>/<summary>` (no library). The **Investigation Timeline** (Trigger→Aggregate→Context→Investigate→Format→Render) reuses the same `.pipe`/`pstage()` visual language as the data-ingestion pipeline strip, for consistency.

### RCA engine v2 — why the output stopped being generic (this session, grounded in live SQL data)
On the real data (Playground.dbo.Input_To_ML, 66,612 rows) the engine returned the **same root cause for every queue**: *"Actual_Offered/Handled is an outlier."* Investigation found three deterministic causes, all fixed in `backend/rca_investigate.py`:
- **Circular evidence.** The offered/handled/adherence fields are outliers for *every* flagged queue by definition — citing them restates the miss, it doesn't explain it. `DEFINITIONAL_FIELDS` + `_verify_and_fix()` now reject any primary whose only evidence is those fields.
- **Noise fields polluted the stats.** `Fiscal_Week` (monotonic, z≈1.9 always), `Week_Ending` (a "categorical change" every week), and the `Monday`..`Sunday` day flags (z>3 any holiday week) were surfacing as spurious "causes"; `Final_Y1..Y5`/`Final_Units` are correlated (one signal counted 5×, fake z≈6). `NOISE_FIELDS` are stripped from the stats sent to the model and `INSTALLED_BASE_FIELDS` collapsed to one `installed_base` signal.
- **Wrong lens for chronic misses.** When a queue is *always* off, the target week isn't an outlier vs its own history, so the model found "nothing" and fell back to restating the miss.

**Two deterministic passes now bracket the model** (`derive_features()` before, `_verify_and_fix()` after). `derive_features()` computes discriminating, per-queue features — chronic bias/level, this-week-vs-usual, forecast-sanity (is the *forecast* the anomaly?), plan restatement, installed-base change, holiday, peer divergence, cleaned signals — and the prompt classifies the miss into a `cause_type` taxonomy (forecast_baseline_error / systematic_forecast_bias / genuine_demand_event / volume_routing_shift / plan_restatement / installed_base_change / calendar_holiday_effect). Verified live: outputs now differ per queue and cite the derived features, never the circular outlier.

**Weak-data rule:** the engine ALWAYS returns the strongest *data-backed* finding (phrased "the data is most consistent with…") with an honest confidence — it never shows "not enough data" and never fabricates. If the LLM produces only a circular/empty answer, `_finding_from_features()` synthesises the primary from the strongest derived feature.

**Per-queue model picker.** `GET /api/models` lists models the backend can actually reach (filtered to providers with a key); the console dropdown re-runs the *same* queue through a chosen model to compare business-acceptability. `POST /api/rca-investigate?provider=&model=` routes to it. A picked model that fails is **not** silently answered by a different model (that would make the comparison dishonest) — the deterministic finding is returned instead, clearly flagged. Reliable set as of this session: `nemotron-3-super-120b` (default), `deepseek-v4-flash`, `llama-3.3-nemotron-super-49b-v1.5`, `nemotron-3-ultra-550b` (flaky/capacity), `llama-3.3-70b-versatile` (Groq). **The NVIDIA `/v1/models` list includes models not provisioned per account** (e.g. `nemotron-ultra-253b` → 404, `deepseek-v4-pro` → timeout) — verify ids per account. Some models reject `response_format:json_object` (nemotron-3-ultra) so `_chat_json` retries without it.

**Severity removed.** The "N× band" tile (`|adherence| ÷ band`) was meaningless to non-analysts and was dropped from the Forecast Summary. Magnitude is still conveyed by Forecast error + Adherence.

**Plain business language + distinct sections.** All human-facing text (Key Findings, Root Cause, Reasoning, Rejected Hypotheses, Recommendations, Missing Info) is written for a business lead — no `z-score`/`stdev`/`outlier`/`trend slope` jargon in the shown text (the prompt translates them). The three sections are deliberately different: **Key Findings** = objective observations, **Root Cause** = the single most-likely *why*, **Reasoning Narrative** = the story (rendered as bullets). Confidence bar is coloured by level (green/amber/red). `_fill_gaps()` populates any section a sparse model reply leaves empty from the derived features, so no card is ever blank.

**Field glossary fed to the model.** `FIELD_DEFINITIONS` (mirrored from the Definitions & Formulas tab — keep the two in sync) is injected as `field_glossary` (only the fields present) into the context the LLM sees, so it interprets fields correctly (e.g. ASU = units under warranty; `Final_Y1..Y5` are nested/overlapping) instead of guessing from column names.

**Data-backed proof, z-scores kept internal.** Business leads distrusted plain sentences with no numbers *and* raw z-scores. Resolution: every finding is backed by the **actual values from the data file** — `derive_features()` builds a `proof` list (forecast, actual, ASU, planned units / shipment, holidays — this-week value, the "usual" 13-week average, and a plain **"vs usual"** phrase like "about 143x higher than usual") rendered as a **"Proof — values from the data"** panel; `supporting_evidence.value` must be a real number (prompt-enforced), never a z-score/deviation. The z-scores still reach the model as *reasoning input*, just never shown. "Usual" = this queue's average over the last **13 weeks** (`RCA_HISTORY_CAP=13`). Evidence chips use dark-blue text for readability, and every sentence must state the number AND its meaning (prompt-enforced) so a manager can read it standalone.

**Forecast-anomaly vs actual-anomaly (correctness).** `forecast_sanity` must not blame the forecast merely because forecast≪actual: a normal forecast with a spiking actual is a **genuine demand event**, not a baseline error. The verdict is `forecast_anomalously_low/high` only when the forecast is off vs its OWN history (|z|>2); when the forecast is normal but the actual is off vs its own history it is `actual_anomalous` → `genuine_demand_event`. The raw forecast/actual ratio is only a fallback when neither field has history to z-test against.

**History comes from the FULL data, never the filtered scan.** RCA history (the "usual" 13-week averages) and peers are gathered from all `ROWS` for the queue (file mode) or a scoped SQL query (`/api/queue-context`, SQL mode) — NOT from `ROWS.filter(passFilters)`. Otherwise an active Fiscal_Week (or any) console filter strips the queue's prior weeks and "usual" renders blank. Bug fixed in `aggregateData` 2026-07-27.

**"Handled" columns are excluded from the RCA.** Accuracy/adherence are defined on OFFERED; `Actual_Handled`/`fcst_handled` (`HANDLED_FIELDS`) are stripped from the model context (statistical_summary, target fields, glossary), the cleaned signals, and the Proof panel — they'd only muddy the analysis. The Proof panel shows a single **Usual (13 wks)** column (the earlier "vs usual" change column was removed at the client's request).

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

## RCA engine v3 — the WFM engine (`?mode=wfm`, branch `wfm-rca`)

A **second, opt-in engine** implementing the business-authored WFM RCA specification. Full
contract, module map, verification and known gaps: **`wfm-rca-engine.md`**. Only the design
decisions worth recording here:

- **Additive, never a replacement.** `POST /api/rca-investigate` without `mode` is byte-for-byte
  the old behaviour. The WFM engine backfills every legacy response key (rank 1 →
  `primary_root_cause`, ranks 2-5 → `secondary_contributors`, rejected challenges →
  `rejected_hypotheses`), so `rca_console.html` needed **zero** changes.
- **Arithmetic is never delegated to the model.** The KPI and the channel-migration verdict are
  computed in Python and *overwrite* whatever the model returned. The model's job is to rank,
  explain in business language, and challenge.
- **Rules the spec stated became code, not prompt text.** "Never conclude below a level before
  checking it isn't inherited" is a computed `inherited_from` verdict from a real SQL rollup.
  "Reject weak explanations" is a feature precondition per cause type — a verdict the data cannot
  support is rejected instead of published. "Ignore weak correlations" is a retain/reject
  threshold. A prompt can request these; only code can guarantee them.
- **One rule was added, not requested.** Check the number is credible *before* explaining it. It
  is surfaced as a hypothesis to validate at source, never as an asserted cause.
- **The CQN definition conflict is unresolved and deliberately visible.** The console's signed-off
  CQN is `Forecast_name + Region + SubRegion + Country + Channel` — channel is *in* the key — while
  the spec wants migration *between channels within* a CQN. Mutually exclusive. The engine does not
  redefine CQN; migration uses a separately named grouping flagged `is_cqn_proxy: true`. Needs a
  business answer (`TODO.md`, P1b).
- **Deterministic fallback is a feature.** If no provider can be reached the report is built from
  the computed signals alone and labelled `wfm-deterministic-fallback`, with the reason in
  `missing_information`. It never fabricates a conclusion to fill the gap.

Note on the Timeline hard-set date above: the "today" marker being pinned to **22 Jul** is now a
tracked defect — the header computes the real date while the legend hardcodes it, so the two
contradict each other on screen (Canary V0.1/V0.2, `TODO.md` P1c).

## RCA engine v4 — the FC Decision Card upgrade (`?mode=spec`, branch `test2`)

Full detail: **`fc-decision-card-engine.md`**. Only the design decisions worth recording here.

- **Enhanced inside the existing architecture, not rewritten.** The 15-step sequence, the ±5%
  threshold, the 23-hypothesis catalogue, the four catalogue states, the driver cascade and the
  eight-dimension confidence model are all untouched. The new deterministic evidence is computed
  between steps 6 and 7, and that position is *forced* rather than chosen: the driver-lag test takes
  the **generated** hypothesis IDs, so it cannot run before step 6, and steps 7–8 collect evidence,
  so it must exist by then. Hypothesis-first stopped being an assertion and became a data dependency.

- **The confidence MODEL was preserved; only its INPUTS improved.** Two dimensions were hardcoded to
  permanently NotApplicable — `HistoricalConsistency` at `(None, 0)` and `ModelAgreement` at
  `(1, 1)`. That was honest when nothing measured precedent and there was only one method. It is no
  longer. Confidence numbers therefore move on some queues; they move because evidence was **found**,
  never because evidence was lost, which is the invariant the model exists to protect.

- **The direction-coherence gate is a business rule, not a filter.** It runs before confidence, and
  when the promoted cause rests only on a mechanism it rejected, `BusinessRuleValidation` scores 0.00
  and Gate 2 caps the level at Low. Arithmetic must not be able to outvote a rule saying the
  conclusion points the wrong way. On live data it duly raised `FORECAST_RESPONSE_FAILURE` from an
  over-response and then rejected it, because the plan sat 42.6% *below* expected — which implies
  actual above plan, while the miss went down.

- **Criticality was added because it did not exist, and it is deliberately not confidence.** The
  absolute contact gap sets the band; the relative gap and persistence can lift it one step and never
  lower it. The absolute gap leads on purpose: a percentage on a tiny queue is arithmetically large
  and operationally irrelevant, which is why the 50-contact materiality floor already existed — and
  that floor is reused as the bottom edge rather than inventing a second, disagreeing threshold.

- **"Not a forecast failure" is a first-class outcome.** `Actual > Forecast` is never on its own a
  forecast failure: all four forecastability conditions must hold, and each is published with the
  figure that decided it. `DEMAND_EVENT_LOW_PREDICTABILITY` gets a recommendation that explicitly
  says *not* to treat it as a model defect — demanding a model change for something no signal
  predicted is advice nobody can act on, and it quietly blames the team for the weather.

- **Coverage discipline is the actual fix.** The arithmetic was never the problem. A z-score of 23.33
  computed from two observations once armed a precondition and shipped a cause at 85% confidence.
  `populated` / `sparse` / `absent` are three different findings with three different actions, they
  are never collapsed, and strength follows coverage rather than magnitude — a sparse driver is never
  Strong evidence however extreme its coefficient.

- **Section 40 became checkable rather than instructed.** The banned-term list is code
  (`decision_card.EXEC_JARGON`), every bullet carries its own `jargon_found`, and the suite asserts
  the executive prose is clean. A style note cannot be tested; a list can.

- **The ranked bullets are evidence, so the model cannot reorder them.** It may reword; a reply that
  reorders is discarded and the deterministic order kept. Rewording is matched **by rank**, not by
  position — matching by position would let a reordered reply attach one bullet's prose to another
  bullet's evidence ID, which is invisible on the rendered card.

- **Two pre-existing bugs meant `?mode=spec` returned HTTP 500 whenever no LLM provider was
  configured.** `_call_llm` returned a 3-tuple where its callers unpack two, and `_narrate` returned
  a 2-tuple where its caller unpacks three — transposed halves of one mistake, both on the
  no-provider path, i.e. exactly the fallback the spec requires to work. Found by running the engine
  offline against an empty config, not by reading it.

- **The first live validation run was contaminated and was discarded.** A uvicorn started hours
  earlier by `run.py` was bound to `0.0.0.0:8000` running pre-upgrade code; on Windows two sockets
  can bind the same port and it is undefined which receives a connection, so requests split between
  the old build and the new one. Nothing errored and the output looked real. The validation script
  now uses a private port, refuses to start if anything is listening on it, and aborts if a completed
  response arrives without `criticality`.
