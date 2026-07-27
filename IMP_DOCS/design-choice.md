# Design Choices — Demand Pattern RCA Console

Why the tool is built the way it is. Read this before changing metrics, charts, or the parser.

## Guiding constraints (from the client scope)
- **Single self-contained HTML file. No external libraries, no CDN, no build step.** The XLSX reader, CSV/TSV parser, filters, metrics and charts are all hand-rolled so the file runs from `file://` or behind Kong with zero dependencies. Keep it that way — do not add a framework.
- **The engine never invents numbers.** Only two metrics are computed, both rule-based. Every figure shown has an ⓘ that reveals the exact formula and inputs. Any narration/LLM layer (on-prem LLaMA) is a *later* phase and must not compute.

## The two metrics (do not add more without sign-off)
| Metric | Formula | Notes |
|---|---|---|
| **Forecast Accuracy** | `Actual_Offered ÷ fcst_offered × 100` | Forecast = `fcst_offered` (ML). |
| **Plan Adherence (ML/Manual)** | `(1 − Actual_Offered ÷ fcst_offered) × 100` | **Signed** (negative = actual ran above forecast/under-forecast, positive = actual ran below forecast/over-forecast) — direction was requested explicitly; ABS was removed. Blank if no actual. |
- Flag rule: **\|Plan-Adherence deviation\| > band %** (default ±10) — the ±band test is a magnitude comparison even though the displayed number is signed. Equivalent to accuracy outside ±band.
- Rows with **no/zero forecast** are data gaps — never scored, never shown as results, counted separately.
- Severity/sort/MAPE (100−MAPE accuracy) all compare on `Math.abs(deviation)` — only the *displayed* number is signed; see `applyAndScan`/`setAccuracy` comments in `rca_console.html`.

## "Avg Accuracy" — the important fix
The old tile averaged `Actual÷Fcst` across rows. Because over- and under-forecasts scatter around 100% and **cancel**, it read ~99% even on genuinely poor data — misleading.
**New definition:** `Avg accuracy = 100 − MAPE`, where MAPE = mean of the per-row absolute % error, which is **exactly the Plan-Adherence deviation** already computed. Clamped at ≥ 0.
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

## Full pipeline: data ingestion → RCA (mockup)
- A **pipeline strip** at the top of the RCA Console visualises the end-to-end path and fills as data flows: **Source → Ingest (rows) → Compute · 2 metrics (scored) → Flag · ±band (flagged) → RCA (ready)**. It's always visible (pending state before load) so the demo tells the whole story at a glance.
- **"🗄 Connect to SQL Server (AA)"** button + modal (Server / Database / Table = `sqlsrv-aa-prod.internal` · `AI_Ready_Data` · `dbo.demand_facts`). Since the mockup has no backend, **Fetch table** ingests the exported file as a stand-in for the live query and tags the source as SQL, so the pipeline's Source stage reads "SQL Server (AA)". In production the same pipeline runs the query directly (no upload) and computes the two metrics server-side — this is Timeline phase 6.
- Source tracking: `window._pendingSrc` ('sql' via the modal, 'file' via Upload) → `window.SRC`, read in `onWeekly`; `renderPipe()` is called on load (pending), on ingest, and after each scan.
- **Evidence trail removed** from the RCA report (was redundant with the Findings bullets + the ⓘ formula/number modal, which remain the source of the math). The report is now: Findings (with ⓘ) → Inputs used → **Root-Cause Investigation** (below).

## Root-Cause Investigation — LLM-driven, replaces the earlier rule-based RCA panel
A prior session built a rule-based "agentic exploration" RCA panel (trend/sibling/discovery-lift/memory, all deterministic JS). **That panel was removed entirely** per client instruction — the client's spec requires the LLM to genuinely reason over the data (generate hypotheses, weigh evidence for/against, reject the unsupported, rank what's left, state confidence and missing information) rather than follow any fixed checklist, deterministic or otherwise. Faking that with rule-based JS presented as "AI reasoning" would violate the client's own design principle: *never fabricate evidence, explicitly state uncertainty.*

**Architecture (matches the client's spec section 7 verbatim), each piece independently testable:**
1. **RCA Trigger** (`triggerRCA`, client-side) — re-validates the row is outside the configured band, then sequences the rest.
2. **Data Aggregator** (`aggregateData`, client-side) — captures the target row's **entire raw field set** generically (`Object.keys(r)` minus our internal `_`-prefixed computed fields — no hardcoded column list), plus prior weeks for the same `Forecast_name` (capped at `RCA_HISTORY_CAP=12` — a token-budget cap, not a business rule) and same-week peers sharing the CQN dims (Region/SubRegion/Country/Channel), different `Forecast_name`.
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

## Timeline / Gantt
The build Gantt lives both **in the app** (Timeline tab, scoped under `#tab-timeline`) and as a **standalone** `rca_timeline.html` (theme-aware light/dark). Keep the two in sync when phase status changes. Today marker and KPIs are currently hard-set to **22 Jul** — update them as the project moves.
